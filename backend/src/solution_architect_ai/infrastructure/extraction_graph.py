from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphRecursionError, InvalidUpdateError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from psycopg import Error
from psycopg_pool import PoolTimeout

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.workflows.extraction_steps import ExtractionSteps


@dataclass
class GraphState:
    run_id: str
    index: int


class ExtractionNode(StrEnum):
    PREPARE = "prepare"
    EXTRACT = "extract"
    MERGE = "merge"
    VERIFY = "verify"
    SAVE = "save"


class GraphThreadConfig(TypedDict):
    thread_id: str


class LangGraphExtraction:
    def __init__(self, steps: ExtractionSteps, checkpointer: AsyncPostgresSaver) -> None:
        self.steps: ExtractionSteps = steps
        graph: StateGraph[GraphState] = StateGraph(GraphState)
        graph.add_node(ExtractionNode.PREPARE, self.prepare)
        graph.add_node(ExtractionNode.EXTRACT, self.extract)
        graph.add_node(ExtractionNode.MERGE, self.validate_completed_parts)
        graph.add_node(ExtractionNode.VERIFY, self.verify)
        graph.add_node(ExtractionNode.SAVE, self.save)
        graph.add_edge(START, ExtractionNode.PREPARE)
        graph.add_edge(ExtractionNode.PREPARE, ExtractionNode.EXTRACT)
        graph.add_conditional_edges(
            ExtractionNode.EXTRACT,
            self.next_node,
            {
                ExtractionNode.EXTRACT: ExtractionNode.EXTRACT,
                ExtractionNode.MERGE: ExtractionNode.MERGE,
            },
        )
        graph.add_edge(ExtractionNode.MERGE, ExtractionNode.VERIFY)
        graph.add_edge(ExtractionNode.VERIFY, ExtractionNode.SAVE)
        graph.add_edge(ExtractionNode.SAVE, END)
        self.graph: CompiledStateGraph[GraphState, None, GraphState, GraphState] = graph.compile(
            checkpointer=checkpointer
        )

    async def run(self, run_id: UUID) -> None:
        try:
            await self.invoke(run_id)
        except (Error, PoolTimeout):
            raise StorageUnavailable("checkpoint_unavailable") from None
        except (ValueError, TypeError, InvalidUpdateError, GraphRecursionError):
            raise StoredExtractionCorrupt("checkpoint_corrupt") from None
        finally:
            self.steps.release_context(run_id)

    async def invoke(self, run_id: UUID) -> None:
        config: RunnableConfig = RunnableConfig(
            configurable=dict(GraphThreadConfig(thread_id=str(run_id))), recursion_limit=1024
        )
        snapshot: object = await self.graph.aget_state(config)
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        if snapshot.values and snapshot.next:
            await self.graph.ainvoke(None, config)
        elif not snapshot.values:
            initial: GraphState = GraphState(str(run_id), 0)
            await self.graph.ainvoke(initial, config)
        else:
            await self.steps.save(run_id)

    async def prepare(self, state: GraphState) -> GraphState:
        await self.steps.prepare(UUID(state.run_id))
        return state

    async def extract(self, state: GraphState) -> GraphState:
        index: int = await self.steps.extract(UUID(state.run_id), state.index)
        return GraphState(state.run_id, index)

    async def next_node(self, state: GraphState) -> ExtractionNode:
        return (
            ExtractionNode.EXTRACT
            if await self.steps.has_more(UUID(state.run_id), state.index)
            else ExtractionNode.MERGE
        )

    async def validate_completed_parts(self, state: GraphState) -> GraphState:
        await self.steps.validate_completed_parts(UUID(state.run_id))
        return state

    async def verify(self, state: GraphState) -> GraphState:
        await self.steps.verify(UUID(state.run_id))
        return state

    async def save(self, state: GraphState) -> GraphState:
        await self.steps.save(UUID(state.run_id))
        return state

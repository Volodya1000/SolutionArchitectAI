from typing import Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from psycopg import Error
from psycopg_pool import PoolTimeout

from solution_architect_ai.application.errors import StorageUnavailable
from solution_architect_ai.application.extraction_steps import ExtractionSteps


class GraphState(TypedDict):
    run_id: str
    index: int


class LangGraphExtraction:
    def __init__(self, steps: ExtractionSteps, checkpointer: AsyncPostgresSaver) -> None:
        self.steps: ExtractionSteps = steps
        graph: StateGraph[GraphState] = StateGraph(GraphState)
        graph.add_node("prepare", self.prepare)
        graph.add_node("extract", self.extract)
        graph.add_node("merge", self.merge)
        graph.add_node("verify", self.verify)
        graph.add_node("save", self.save)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "extract")
        graph.add_conditional_edges(
            "extract", self.next_node, {"extract": "extract", "merge": "merge"}
        )
        graph.add_edge("merge", "verify")
        graph.add_edge("verify", "save")
        graph.add_edge("save", END)
        self.graph: CompiledStateGraph[GraphState, None, GraphState, GraphState] = graph.compile(
            checkpointer=checkpointer
        )

    async def run(self, run_id: UUID) -> None:
        try:
            await self.invoke(run_id)
        except (Error, PoolTimeout):
            raise StorageUnavailable("checkpoint_unavailable") from None

    async def invoke(self, run_id: UUID) -> None:
        config: RunnableConfig = {
            "configurable": {"thread_id": str(run_id)},
            "recursion_limit": 1024,
        }
        snapshot: object = await self.graph.aget_state(config)
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        if snapshot.values and snapshot.next:
            await self.graph.ainvoke(None, config)
        elif not snapshot.values:
            initial: GraphState = {"run_id": str(run_id), "index": 0}
            await self.graph.ainvoke(initial, config)
        else:
            await self.steps.save(run_id)

    async def prepare(self, state: GraphState) -> GraphState:
        await self.steps.prepare(UUID(state["run_id"]))
        return state

    async def extract(self, state: GraphState) -> GraphState:
        index: int = await self.steps.extract(UUID(state["run_id"]), state["index"])
        return {"run_id": state["run_id"], "index": index}

    async def next_node(self, state: GraphState) -> Literal["extract", "merge"]:
        return (
            "extract"
            if await self.steps.has_more(UUID(state["run_id"]), state["index"])
            else "merge"
        )

    async def merge(self, state: GraphState) -> GraphState:
        await self.steps.merge(UUID(state["run_id"]))
        return state

    async def verify(self, state: GraphState) -> GraphState:
        await self.steps.verify(UUID(state["run_id"]))
        return state

    async def save(self, state: GraphState) -> GraphState:
        await self.steps.save(UUID(state["run_id"]))
        return state

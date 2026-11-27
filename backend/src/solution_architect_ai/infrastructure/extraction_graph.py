from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphRecursionError, InvalidUpdateError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot, interrupt
from psycopg import Error
from psycopg_pool import PoolTimeout

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.workflows.clarification_workflow import ClarificationWorkflow
from solution_architect_ai.application.workflows.extraction_steps import ExtractionSteps


@dataclass
class GraphState:
    run_id: str
    index: int
    cycle: int = 0
    clarification_only: bool = False


class ExtractionNode(StrEnum):
    PREPARE = "prepare"
    EXTRACT = "extract"
    MERGE = "merge"
    VERIFY = "verify"
    SAVE = "save"
    CLARIFY = "clarify"
    WAIT_INPUT = "wait_input"
    COMPLETE = "complete"


class GraphThreadConfig(TypedDict):
    thread_id: str


class LangGraphExtraction:
    def __init__(
        self,
        steps: ExtractionSteps,
        checkpointer: AsyncPostgresSaver,
        workflow: ClarificationWorkflow | None = None,
    ) -> None:
        self.steps: ExtractionSteps = steps
        self.workflow: ClarificationWorkflow | None = workflow
        graph: StateGraph[GraphState] = StateGraph(GraphState)
        graph.add_node(ExtractionNode.PREPARE, self.prepare)
        graph.add_node(ExtractionNode.EXTRACT, self.extract)
        graph.add_node(ExtractionNode.MERGE, self.validate_completed_parts)
        graph.add_node(ExtractionNode.VERIFY, self.verify)
        graph.add_node(ExtractionNode.SAVE, self.save)
        graph.add_conditional_edges(
            START,
            self.entry_node,
            {
                ExtractionNode.PREPARE: ExtractionNode.PREPARE,
                ExtractionNode.WAIT_INPUT: ExtractionNode.WAIT_INPUT,
            },
        )
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
        graph.add_node(ExtractionNode.CLARIFY, self.clarify)
        graph.add_node(ExtractionNode.WAIT_INPUT, self.wait_input)
        graph.add_node(ExtractionNode.COMPLETE, self.complete)
        graph.add_edge(ExtractionNode.SAVE, ExtractionNode.CLARIFY)
        graph.add_edge(ExtractionNode.CLARIFY, ExtractionNode.WAIT_INPUT)
        graph.add_edge(ExtractionNode.WAIT_INPUT, ExtractionNode.COMPLETE)
        graph.add_edge(ExtractionNode.COMPLETE, END)
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
        if self.workflow is not None:
            await self.invoke_clarification_graph(run_id, config, snapshot)
            return
        if snapshot.values and snapshot.next:
            await self.graph.ainvoke(None, config)
        elif not snapshot.values:
            initial: GraphState = GraphState(str(run_id), 0)
            await self.graph.ainvoke(initial, config)
        else:
            await self.steps.save(run_id)

    async def invoke_clarification_graph(
        self, run_id: UUID, config: RunnableConfig, snapshot: object
    ) -> None:
        if self.workflow is None:
            return
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        view: ClarificationView = await self.workflow.get(run_id)
        if not snapshot.values:
            await self.graph.ainvoke(GraphState(str(run_id), 0), config)
        else:
            await self._continue_clarification_graph(run_id, config, snapshot, view)
        await self.workflow.acknowledge(run_id, view.resume_version)

    async def _continue_clarification_graph(
        self, run_id: UUID, config: RunnableConfig, snapshot: object, view: ClarificationView
    ) -> None:
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        completed: bool = any(cycle.cycle == view.cycle for cycle in view.completed_cycles)
        if self.checkpoint_cycle(snapshot, run_id, view.cycle) != view.cycle:
            await self.graph.ainvoke(GraphState(str(run_id), 0, view.cycle, True), config)
        elif snapshot.next:
            await self.resume_checkpoint(config, snapshot, view)
        elif view.initialized and not completed:
            await self.graph.ainvoke(GraphState(str(run_id), 0, view.cycle, True), config)

    @staticmethod
    def checkpoint_cycle(snapshot: object, run_id: UUID, current_cycle: int) -> int:
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        values: object = snapshot.values
        if not isinstance(values, dict) or values.get("run_id") != str(run_id):
            raise TypeError("Invalid checkpoint run")
        value: object = values.get("cycle", 0)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= current_cycle:
            raise TypeError("Invalid checkpoint clarification cycle")
        return value

    async def resume_checkpoint(
        self, config: RunnableConfig, snapshot: object, view: ClarificationView
    ) -> None:
        if not isinstance(snapshot, StateSnapshot):
            raise TypeError("Invalid graph snapshot")
        if not any(task.interrupts for task in snapshot.tasks):
            await self.graph.ainvoke(None, config)
            return
        if self._resume_ready(view):
            await self.graph.ainvoke(
                Command(
                    resume={
                        "run_id": str(view.run_id),
                        "cycle": view.cycle,
                        "resume_version": view.resume_version,
                    }
                ),
                config,
            )

    @staticmethod
    def _resume_ready(view: ClarificationView) -> bool:
        if view.resume_pending and view.resume_version > 0:
            return True
        return view.initialized and not any(
            question.blocking and question.status == "open" for question in view.questions
        )

    async def entry_node(self, state: GraphState) -> ExtractionNode:
        return ExtractionNode.WAIT_INPUT if state.clarification_only else ExtractionNode.PREPARE

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
        if self.workflow is not None:
            await self.steps.save_candidates(UUID(state.run_id))
        else:
            await self.steps.save(UUID(state.run_id))
        return state

    async def clarify(self, state: GraphState) -> GraphState:
        if self.workflow is not None:
            await self.workflow.prepare_questions(UUID(state.run_id))
        return state

    async def wait_input(self, state: GraphState) -> GraphState:
        if self.workflow is None:
            return state
        view: ClarificationView = await self.workflow.get(UUID(state.run_id))
        while any(question.blocking and question.status == "open" for question in view.questions):
            await self.workflow.waiting(UUID(state.run_id))
            interrupt(
                {
                    "run_id": state.run_id,
                    "cycle": view.cycle,
                    "question_ids": [
                        str(question.id) for question in view.questions if question.status == "open"
                    ],
                }
            )
            view = await self.workflow.get(UUID(state.run_id))
        return GraphState(state.run_id, state.index, view.cycle, state.clarification_only)

    async def complete(self, state: GraphState) -> GraphState:
        if self.workflow is not None:
            await self.workflow.complete(UUID(state.run_id), state.cycle)
        return state

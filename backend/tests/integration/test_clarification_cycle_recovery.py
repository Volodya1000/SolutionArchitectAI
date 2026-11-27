import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import StateSnapshot

from backend.tests.integration.test_clarification_graph import (
    DOCUMENT,
    answer,
    install_questions,
    start_fresh,
)
from backend.tests.integration.test_extraction_lifecycle import ExtractionResources, upload
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.models.clarification_models import (
    ClarificationView,
    DecisionResult,
    ResolveAssumption,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStore,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.clarification_workflow import ClarificationWorkflow
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.extraction_graph import LangGraphExtraction

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class CycleCase:
    resources: ExtractionResources
    run_id: UUID
    worker: ExtractionWorker
    service: ClarificationService
    graph: LangGraphExtraction
    workflow: ClarificationWorkflow
    decision: DecisionResult
    requests: int

    async def reject(self) -> None:
        await self.service.resolve(
            self.decision.decision_id,
            ResolveAssumption(
                operation_id=uuid4(),
                expected_revision=1,
                resolution="reject",
                reason="Заказчик отклонил исходное допущение",
            ),
        )

    async def pending_nodes(self) -> tuple[str, ...]:
        config: RunnableConfig = {"configurable": {"thread_id": str(self.run_id)}}
        snapshot: object = await self.graph.graph.aget_state(config)
        assert isinstance(snapshot, StateSnapshot)
        return snapshot.next


@pytest.fixture(name="cycle_case")
async def cycle_case_fixture(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> CycleCase:
    await install_questions(resources, monkeypatch, count=1)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    service: ClarificationService = await resources.container.get(ClarificationService)
    view: ClarificationView = await service.get(run.id)
    decision: DecisionResult = await service.answer(
        run.id, view.questions[0].id, answer(view.questions[0], assumption=True)
    )
    graph: object = worker.graph
    assert isinstance(graph, LangGraphExtraction)
    assert graph.workflow is not None
    return CycleCase(
        resources,
        run.id,
        worker,
        service,
        graph,
        graph.workflow,
        decision,
        (await resources.view(run.id)).requests,
    )


async def assert_new_cycle_waits_and_completes(case: CycleCase) -> None:
    await case.worker.execute(case.run_id)
    waiting: ClarificationView = await case.service.get(case.run_id)
    assert waiting.cycle == 1
    assert waiting.questions[0].revision == 2
    assert waiting.questions[0].status == "open"
    assert waiting.decisions[0].resolution == "rejected"
    assert (await case.resources.view(case.run_id)).status == RunStatus.WAITING_INPUT
    assert await case.pending_nodes() == ("wait_input",)
    assert (await case.resources.view(case.run_id)).requests == case.requests
    await case.service.answer(case.run_id, waiting.questions[0].id, answer(waiting.questions[0]))
    await case.worker.execute(case.run_id)
    completed: ClarificationView = await case.service.get(case.run_id)
    assert (await case.resources.view(case.run_id)).status == RunStatus.COMPLETED
    assert [cycle.cycle for cycle in completed.completed_cycles] == [0, 1]
    assert not completed.resume_pending
    assert (await case.resources.view(case.run_id)).requests == case.requests
    assert not await case.pending_nodes()


async def test_rejection_supersedes_old_complete_checkpoint_after_sql_commit(
    cycle_case: CycleCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    original: Callable[[UUID, int], Awaitable[None]] = cycle_case.workflow.complete

    async def lose_completion_checkpoint(run_id: UUID, expected_cycle: int) -> None:
        await original(run_id, expected_cycle)
        raise StorageUnavailable("checkpoint_unavailable")

    monkeypatch.setattr(cycle_case.workflow, "complete", lose_completion_checkpoint)
    await cycle_case.worker.execute(cycle_case.run_id)
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.COMPLETED
    assert [
        cycle.cycle for cycle in (await cycle_case.service.get(cycle_case.run_id)).completed_cycles
    ] == [0]
    assert await cycle_case.pending_nodes() == ("complete",)
    await cycle_case.reject()
    monkeypatch.setattr(cycle_case.workflow, "complete", original)
    checkpointer: object = cycle_case.graph.graph.checkpointer
    assert isinstance(checkpointer, AsyncPostgresSaver)
    cycle_case.worker.graph = LangGraphExtraction(
        cycle_case.graph.steps, checkpointer, cycle_case.workflow
    )
    await assert_new_cycle_waits_and_completes(cycle_case)


async def test_rejection_racing_inflight_old_completion_cannot_complete_or_fail_new_cycle(
    cycle_case: CycleCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Persist cycle zero in SQL while leaving COMPLETE as the pending checkpoint node.
    original: Callable[[UUID, int], Awaitable[None]] = cycle_case.workflow.complete
    await original(cycle_case.run_id, 0)
    entered: asyncio.Event = asyncio.Event()
    release: asyncio.Event = asyncio.Event()

    async def pause_before_old_completion(run_id: UUID, expected_cycle: int) -> None:
        entered.set()
        await release.wait()
        await original(run_id, expected_cycle)

    monkeypatch.setattr(cycle_case.workflow, "complete", pause_before_old_completion)
    completion: asyncio.Task[None] = asyncio.create_task(
        cycle_case.worker.execute(cycle_case.run_id)
    )
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            await cycle_case.reject()
            release.set()
            await completion
    finally:
        release.set()
        await asyncio.gather(completion, return_exceptions=True)
    interrupted: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.WAITING_INPUT
    assert interrupted.resume_pending
    assert interrupted.cycle == 1
    assert [cycle.cycle for cycle in interrupted.completed_cycles] == [0]
    monkeypatch.setattr(cycle_case.workflow, "complete", original)
    await assert_new_cycle_waits_and_completes(cycle_case)


async def test_obsolete_sql_completion_cannot_complete_answered_reopened_cycle(
    cycle_case: CycleCase,
) -> None:
    await cycle_case.workflow.complete(cycle_case.run_id, 0)
    await cycle_case.reject()
    reopened: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    await cycle_case.service.answer(
        cycle_case.run_id, reopened.questions[0].id, answer(reopened.questions[0])
    )
    before: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    extraction: ExtractionView = await cycle_case.resources.view(cycle_case.run_id)
    await cycle_case.workflow.complete(cycle_case.run_id, 0)
    assert await cycle_case.service.get(cycle_case.run_id) == before
    assert await cycle_case.resources.view(cycle_case.run_id) == extraction
    assert extraction.status == RunStatus.WAITING_INPUT
    assert [cycle.cycle for cycle in before.completed_cycles] == [0]
    await cycle_case.worker.execute(cycle_case.run_id)
    completed: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    assert [cycle.cycle for cycle in completed.completed_cycles] == [0, 1]
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.COMPLETED
    assert (await cycle_case.resources.view(cycle_case.run_id)).requests == cycle_case.requests


async def test_obsolete_cycle_completion_does_not_revalidate_source(
    cycle_case: CycleCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    await cycle_case.workflow.complete(cycle_case.run_id, 0)
    await cycle_case.reject()
    before: ClarificationView = await cycle_case.service.get(cycle_case.run_id)

    async def forbidden_read(_version_id: UUID) -> bytes:
        raise AssertionError("Obsolete completion must stop before source access")

    monkeypatch.setattr(cycle_case.workflow.steps.documents, "read", forbidden_read)
    await cycle_case.workflow.complete(cycle_case.run_id, 0)
    assert await cycle_case.service.get(cycle_case.run_id) == before
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.WAITING_INPUT


async def test_worker_recovery_requeues_waiting_answer_through_clarification_store(
    cycle_case: CycleCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cycle_case.worker.clarifications is not None
    view: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    store: ClarificationStore
    async with cycle_case.worker.clarifications.open() as store:
        await store.acknowledge(cycle_case.run_id, view.resume_version)
    assert not (await cycle_case.service.get(cycle_case.run_id)).resume_pending

    async def dispatch_target(group: asyncio.TaskGroup) -> None:
        # Other integration cases retain pending rows; isolate dispatch, not SQL recovery.
        await cycle_case.worker.dispatch_run(
            group, await cycle_case.resources.view(cycle_case.run_id)
        )

    monkeypatch.setattr(cycle_case.worker, "dispatch", dispatch_target)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        await cycle_case.worker.poll(group)
    assert cycle_case.worker.recovered
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.COMPLETED
    assert (await cycle_case.resources.view(cycle_case.run_id)).requests == cycle_case.requests
    assert not cycle_case.worker.active


async def test_scheduler_resumes_closed_blockers_without_local_resume_marker(
    cycle_case: CycleCase,
) -> None:
    assert cycle_case.worker.clarifications is not None
    view: ClarificationView = await cycle_case.service.get(cycle_case.run_id)
    clarification_store: ClarificationStore
    async with cycle_case.worker.clarifications.open() as clarification_store:
        await clarification_store.acknowledge(cycle_case.run_id, view.resume_version)
    assert not (await cycle_case.service.get(cycle_case.run_id)).resume_pending
    extraction_store: ExtractionStore
    async with cycle_case.resources.stores.open() as extraction_store:
        assert cycle_case.run_id in {item.id for item in await extraction_store.pending()}
    await cycle_case.worker.execute(cycle_case.run_id)
    assert (await cycle_case.resources.view(cycle_case.run_id)).status == RunStatus.COMPLETED
    assert (await cycle_case.resources.view(cycle_case.run_id)).requests == cycle_case.requests
    async with cycle_case.resources.stores.open() as extraction_store:
        assert cycle_case.run_id not in {item.id for item in await extraction_store.pending()}

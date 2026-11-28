import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.clarification_graph import (
    DOCUMENT,
    answer,
    install_questions,
    start_fresh,
)
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.sql_store_setup import SqlStoreSetup, clarification_store_setup
from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    AnswerClarification,
    ClarificationView,
    DecisionResult,
    ResolveAssumption,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionGraph
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.extraction_graph import LangGraphExtraction
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def test_two_independent_blockers_apply_first_answer_before_global_completion(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.WAITING_INPUT
    first: ClarificationView = await service.get(run.id)
    assert len(first.questions) == 2
    await service.answer(run.id, first.questions[0].id, answer(first.questions[0]))
    partial: ClarificationView = await service.get(run.id)
    assert partial.questions[1].status == "open"
    assert any(
        "Сохранить условие архитектора" in requirement.normalized_text
        for requirement in partial.requirements
    )
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.WAITING_INPUT
    await service.answer(run.id, first.questions[1].id, answer(first.questions[1]))
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    assert len((await service.get(run.id)).completed_cycles) == 1
    assert not worker.active


async def test_reject_after_completed_checkpoint_starts_new_cycle_without_extraction(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch, count=1)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run.id)
    first: ClarificationView = await service.get(run.id)
    decision: DecisionResult = await service.answer(
        run.id, first.questions[0].id, answer(first.questions[0], assumption=True)
    )
    await worker.execute(run.id)
    completed: ClarificationView = await service.get(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    requests: int = (await resources.view(run.id)).requests
    await service.resolve(
        decision.decision_id,
        ResolveAssumption(
            operation_id=uuid4(),
            expected_revision=1,
            resolution="reject",
            reason="Заказчик изменил решение",
        ),
    )
    await worker.execute(run.id)
    reopened: ClarificationView = await service.get(run.id)
    assert reopened.cycle == 1
    assert reopened.completed_cycles == completed.completed_cycles
    assert reopened.questions[0].revision == 2
    assert reopened.decisions[0].resolution_reason == "Заказчик изменил решение"
    assert (await resources.view(run.id)).status == RunStatus.WAITING_INPUT
    await service.answer(run.id, reopened.questions[0].id, answer(reopened.questions[0]))
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    assert (await resources.view(run.id)).requests == requests
    assert len((await service.get(run.id)).completed_cycles) == 2


async def test_answer_committed_before_checkpoint_is_recovered_by_new_graph(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch, count=1)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run.id)
    view: ClarificationView = await service.get(run.id)
    command: AnswerClarification = answer(view.questions[0])
    decision: DecisionResult = await service.answer(run.id, view.questions[0].id, command)
    graph: ExtractionGraph = worker.extraction_graph
    assert isinstance(graph, LangGraphExtraction)

    async def lose_checkpoint(_run_id: UUID) -> None:
        raise StorageUnavailable("checkpoint_unavailable")

    monkeypatch.setattr(graph, "invoke", lose_checkpoint)
    await worker.execute(run.id)
    assert (await service.get(run.id)).resume_pending
    checkpointer: object = graph.state_graph.checkpointer
    assert isinstance(checkpointer, AsyncPostgresSaver)
    worker.extraction_graph = LangGraphExtraction(
        graph.extraction_steps, checkpointer, graph.clarification_workflow
    )
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    assert await service.answer(run.id, view.questions[0].id, command) == decision
    assert len((await service.get(run.id)).decisions) == 1


async def test_waiting_releases_resources_and_next_day_does_not_exhaust_budget(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch, count=1)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run.id)
    assert not worker.capacity.slots.locked()
    assert not worker.active
    stores: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        await resources.container.get(async_sessionmaker[AsyncSession]),
        await resources.container.get(ActorContext),
    )
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        state: ClarificationRunRow = await store.run(run.id)
        assert state.active_started is None
        assert state.active_seconds < worker.deadline
        assert (
            await store.session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'"
                )
            )
            == 0
        )
        extraction: ExtractionRow = await store.extraction(run.id)
        snapshot: ExtractionView = ExtractionView.model_validate_json(extraction.snapshot_json)
        snapshot.created_at = datetime.now(UTC) - timedelta(days=2)
        extraction.created_at, extraction.snapshot_json = (
            snapshot.created_at,
            snapshot.model_dump_json(),
        )
    view: ClarificationView = await service.get(run.id)
    await service.answer(run.id, view.questions[0].id, answer(view.questions[0]))
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    assert (await resources.view(run.id)).elapsed_seconds < worker.deadline


async def test_nonblocking_question_remains_visible_after_completion(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch, count=1, blocking=False)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    service: ClarificationService = await resources.container.get(ClarificationService)
    view: ClarificationView = await service.get(run.id)
    assert (await resources.view(run.id)).status == RunStatus.COMPLETED
    assert view.questions[0].status == "open"
    assert not view.questions[0].blocking


@pytest.mark.parametrize("cancel", [False, True])
async def test_resumed_failure_or_cancellation_retains_human_decision(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    await install_questions(resources, monkeypatch, count=1)
    version: DocumentVersionView = await upload(resources, DOCUMENT)
    run: ExtractionView = await start_fresh(resources, version.version_id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run.id)
    view: ClarificationView = await service.get(run.id)
    await service.answer(run.id, view.questions[0].id, answer(view.questions[0]))
    graph: ExtractionGraph = worker.extraction_graph
    assert isinstance(graph, LangGraphExtraction)
    assert graph.clarification_workflow is not None
    entered: asyncio.Event = asyncio.Event()

    async def failing_complete(_run_id: UUID, _expected_cycle: int) -> None:
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise StructuredGenerationFailure(StructuredErrorCode.UNAVAILABLE)

    monkeypatch.setattr(graph.clarification_workflow, "complete", failing_complete)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        await worker.dispatch_run(group, await resources.view(run.id))
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            await resources.service.cancel(run.id)
            await worker.dispatch_run(group, await resources.view(run.id))
    assert (await resources.view(run.id)).status == (
        RunStatus.CANCELLED if cancel else RunStatus.FAILED
    )
    assert len((await service.get(run.id)).decisions) == 1
    assert not worker.capacity.slots.locked()

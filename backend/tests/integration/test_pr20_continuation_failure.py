import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.clarification_graph import install_questions, start_fresh
from backend.test_helpers.clarification_history import seed_analysis
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.continuation_resources import (
    ContinuationResources,
    isolated_continuation_resources,
)
from backend.test_helpers.document_builders import document
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.models.clarification_models import (
    ClarificationView,
    ResumeRun,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
    RequirementView,
)
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class CompletedContinuation:
    run_id: UUID
    before: ClarificationView
    resume_version: int


async def seed_completed_continuation(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    source: ParsedDocument | None = None,
    config_digest: str | None = None,
) -> CompletedContinuation:
    missing_source: ParsedDocument = source or document(
        uuid4(), "Completed source no longer available"
    )
    requirement: RequirementView = referenced_requirement(
        missing_source, missing_source.fragments[0]
    )
    run_id: UUID = await seed_analysis(stores, missing_source, requirement)
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        if config_digest is not None:
            (await store.extraction(run_id)).config_digest = config_digest
        await store.save_questions(run_id, [])
        await store.complete_cycle(run_id, 0)
        before: ClarificationView = await store.get(run_id)
        await store.resume(
            run_id, ResumeRun(operation_id=uuid4(), question_revisions={}, source_versions=[])
        )
        return CompletedContinuation(run_id, before, await store.get_resume_version(run_id))


@pytest.fixture(name="continuation_resources")
async def continuation_resources_fixture(
    resources: ExtractionResources, decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore]
) -> AsyncGenerator[ContinuationResources]:
    isolated: ContinuationResources
    async with isolated_continuation_resources(resources, decision_stores) as isolated:
        yield isolated


@dataclass
class QueueExecutionTrace:
    task_id: UUID
    initial_pending: list[UUID]
    ambient_pending: list[UUID]
    attempted: list[UUID] = field(default_factory=list)

    def diagnostic(self, remaining: list[UUID]) -> str:
        return "execution_trace " + json.dumps(
            {
                "task_id": str(self.task_id),
                "initial_pending": [str(item) for item in self.initial_pending],
                "attempted": [str(item) for item in self.attempted],
                "remaining_pending": [str(item) for item in remaining],
                "ambient_default_task_pending": [str(item) for item in self.ambient_pending],
            }
        )


async def pending_ids(resources: ExtractionResources) -> list[UUID]:
    store: ExtractionStore
    async with resources.stores.open() as store:
        return [item.id for item in await store.pending()]


async def seed_scoped_missing_source(case: ContinuationResources) -> CompletedContinuation:
    version: DocumentVersionView = await upload(case.resources, "Previously completed source")
    source: ParsedDocument = await case.resources.documents.get_parsed_document(version.version_id)
    policy: ExtractionPolicy = await case.resources.container.get(ExtractionPolicy)
    completed: CompletedContinuation = await seed_completed_continuation(
        case.stores, source, policy.config_digest
    )
    source_path: Path = (case.resources.settings.storage.root / version.storage_key).resolve()
    assert source_path.is_relative_to(case.resources.settings.storage.root.resolve())
    await asyncio.to_thread(source_path.unlink)
    return completed


async def serve_until_completed(
    case: ContinuationResources, monkeypatch: pytest.MonkeyPatch, poisoned_id: UUID, run_id: UUID
) -> QueueExecutionTrace:
    resources: ExtractionResources = case.resources
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    terminal: asyncio.Event = asyncio.Event()
    trace: QueueExecutionTrace = QueueExecutionTrace(
        case.stores.actor.task_id, await pending_ids(resources), case.ambient_pending
    )
    assert trace.initial_pending == [poisoned_id, run_id], trace.diagnostic(trace.initial_pending)
    original_execute: Callable[[UUID], Awaitable[None]] = worker.execute

    async def execute(identifier: UUID) -> None:
        trace.attempted.append(identifier)
        await original_execute(identifier)
        if (
            identifier == run_id
            and (await resources.view(identifier)).status == RunStatus.COMPLETED
        ):
            terminal.set()
        if trace.attempted.count(poisoned_id) > 1:
            terminal.set()

    monkeypatch.setattr(worker, "execute", execute)
    serving: asyncio.Task[None] = asyncio.create_task(worker.serve())
    timed_out: bool = False
    try:
        async with asyncio.timeout(30):
            await terminal.wait()
    except TimeoutError:
        timed_out = True
    finally:
        worker.stopping.set()
        await serving
    remaining: list[UUID] = await pending_ids(resources)
    diagnostic: str = trace.diagnostic(remaining)
    assert not timed_out, diagnostic
    assert trace.attempted == [poisoned_id, run_id], diagnostic
    assert not remaining, diagnostic
    return trace


async def test_failed_completed_continuation_is_diagnosed_without_starving_queued_neighbor(
    continuation_resources: ContinuationResources,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources: ExtractionResources = continuation_resources.resources
    completed: CompletedContinuation = await seed_scoped_missing_source(continuation_resources)
    await install_questions(resources, monkeypatch, count=0)
    version_id: UUID = (await upload(resources, "Система должна сохранять отчёты.")).version_id
    neighbor: ExtractionView = await start_fresh(resources, version_id)
    trace: QueueExecutionTrace = await serve_until_completed(
        continuation_resources, monkeypatch, completed.run_id, neighbor.id
    )
    assert trace.attempted.count(completed.run_id) == 1
    assert (await resources.view(neighbor.id)).status == RunStatus.COMPLETED
    store: SqlAlchemyClarificationStore
    async with continuation_resources.stores.open() as store:
        after: ClarificationView = await store.get(completed.run_id)
        poisoned: ExtractionView = ExtractionView.model_validate_json(
            (await store.extraction(completed.run_id)).snapshot_json
        )
        assert poisoned.status == RunStatus.COMPLETED
        assert poisoned.error_code == "document_file_missing"
        assert poisoned.requirements == completed.before.requirements
        assert after.completed_cycles == completed.before.completed_cycles
        assert not after.resume_pending


async def test_repeated_poisoned_continuation_is_detected_without_waiting_for_timeout(
    continuation_resources: ContinuationResources,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed: CompletedContinuation = await seed_scoped_missing_source(continuation_resources)
    await install_questions(continuation_resources.resources, monkeypatch, count=0)
    version: DocumentVersionView = await upload(
        continuation_resources.resources, "Система должна сохранять отчёты."
    )
    neighbor: ExtractionView = await start_fresh(
        continuation_resources.resources, version.version_id
    )
    failed_attempts: list[UUID] = []

    async def leave_pending(
        _store: SqlAlchemyClarificationStore, run_id: UUID, _expected_version: int, _code: str
    ) -> None:
        failed_attempts.append(run_id)

    monkeypatch.setattr(SqlAlchemyClarificationStore, "fail_continuation", leave_pending)
    with pytest.raises(AssertionError, match="execution_trace"):
        await serve_until_completed(
            continuation_resources, monkeypatch, completed.run_id, neighbor.id
        )
    assert failed_attempts == [completed.run_id, completed.run_id]
    assert (await continuation_resources.resources.view(neighbor.id)).status == RunStatus.QUEUED


async def test_old_failure_cannot_acknowledge_a_newer_resume_and_success_clears_diagnostic(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    completed: CompletedContinuation = await seed_completed_continuation(decision_stores)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        await store.resume(
            completed.run_id,
            ResumeRun(operation_id=uuid4(), question_revisions={}, source_versions=[]),
        )
        await store.fail_continuation(completed.run_id, completed.resume_version, "old_failure")
        newer: ClarificationView = await store.get(completed.run_id)
        assert newer.resume_pending
        assert newer.resume_version == completed.resume_version + 1
        await store.fail_continuation(completed.run_id, newer.resume_version, "source_unavailable")
    async with decision_stores.open() as store:
        failed: ClarificationView = await store.get(completed.run_id)
        assert not failed.resume_pending
        assert (
            ExtractionView.model_validate_json(
                (await store.extraction(completed.run_id)).snapshot_json
            ).error_code
            == "source_unavailable"
        )
        await store.complete_cycle(completed.run_id, 0)
    async with decision_stores.open() as store:
        recovered: ExtractionView = ExtractionView.model_validate_json(
            (await store.extraction(completed.run_id)).snapshot_json
        )
        assert recovered.error_code is None
        assert recovered.status == RunStatus.COMPLETED
        assert (
            await store.get(completed.run_id)
        ).completed_cycles == completed.before.completed_cycles

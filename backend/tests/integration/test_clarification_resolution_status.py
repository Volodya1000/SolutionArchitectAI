import asyncio
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.tests.integration.test_clarification_commands import (  # pylint: disable=unused-import,useless-import-alias
    decision_stores_fixture as decision_stores_fixture,
)
from backend.tests.integration.test_clarification_commands import seed_run, wait_for_database_lock
from backend.tests.integration.test_clarification_http import HttpCase, answer_command
from backend.tests.integration.test_clarification_http import (  # pylint: disable=unused-import,useless-import-alias
    http_case_fixture as http_case_fixture,
)
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from backend.tests.sql_store_setup import (
    SqlStoreSetup,
    extraction_store_setup,
)
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    ResolveAssumption,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
    QuestionRevisionRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class ResolutionCase:
    stores: SqlStoreSetup[SqlAlchemyClarificationStore]
    run_id: UUID
    decision: DecisionResult

    async def stop(self, status: RunStatus) -> None:
        extraction_stores: SqlStoreSetup[SqlAlchemyExtractionStore] = extraction_store_setup(
            self.stores.sessions, task_id=self.stores.actor.task_id
        )
        store: ExtractionStore
        async with extraction_stores.open() as store:
            await store.set_status(self.run_id, status)


@dataclass(frozen=True)
class ResolutionSnapshot:
    view: ClarificationView
    extraction_status: str
    extraction_json: str
    revision_count: int
    operation_json: str | None


@pytest.fixture(name="resolution_case")
async def resolution_case_fixture(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> ResolutionCase:
    run_id: UUID = uuid4()
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"terminal-resolution:{run_id}",
        text="Как обрабатывать отказ?",
        basis="Условие не определено",
        dependent_decision="Обработка отказа",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    await seed_run(decision_stores, run_id, question)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        decision: DecisionResult = await store.answer(
            run_id,
            question.id,
            AnswerClarification(
                operation_id=uuid4(),
                expected_question_revision=1,
                source_versions=[],
                kind="assumption",
                text="Повторить операцию",
                basis="До согласования заказчиком",
                assumption=AssumptionDetails(
                    responsible="Архитектор",
                    verification_condition="До реализации",
                    consequences="Повторная обработка",
                    mitigation="Контролировать уникальность",
                ),
            ),
        )
    return ResolutionCase(decision_stores, run_id, decision)


def resolution_command(resolution: Literal["confirm", "reject"]) -> ResolveAssumption:
    return ResolveAssumption(
        operation_id=uuid4(),
        expected_revision=1,
        resolution=resolution,
        reason="Заказчик проверил допущение",
    )


async def snapshot(case: ResolutionCase, operation_id: UUID) -> ResolutionSnapshot:
    store: SqlAlchemyClarificationStore
    async with case.stores.open() as store:
        extraction: ExtractionRow = await store.extraction(case.run_id)
        revision_count: int | None = await store.session.scalar(
            select(func.count())
            .select_from(QuestionRevisionRow)
            .where(QuestionRevisionRow.question_id == case.decision.question_id)
        )
        assert revision_count is not None
        operation: ClarificationOperationRow | None = await store.session.get(
            ClarificationOperationRow, (case.stores.actor.task_id, operation_id)
        )
        return ResolutionSnapshot(
            await store.get(case.run_id),
            extraction.status,
            extraction.snapshot_json,
            revision_count,
            operation.result_json if operation is not None else None,
        )


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED])
@pytest.mark.parametrize("resolution", ["confirm", "reject"])
async def test_new_resolution_cannot_mutate_cancelled_cancelling_or_failed_analysis(
    resolution_case: ResolutionCase,
    status: RunStatus,
    resolution: Literal["confirm", "reject"],
) -> None:
    await resolution_case.stop(status)
    command: ResolveAssumption = resolution_command(resolution)
    before: ResolutionSnapshot = await snapshot(resolution_case, command.operation_id)
    store: SqlAlchemyClarificationStore
    with pytest.raises(Conflict, match="extraction_not_resumable"):
        async with resolution_case.stores.open() as store:
            await store.resolve(resolution_case.decision.decision_id, command)
    assert await snapshot(resolution_case, command.operation_id) == before
    assert before.extraction_status == status.value
    assert before.view.decisions[0].resolution == "pending"
    assert before.view.risks[0].status == "open"
    assert before.revision_count == 1
    assert before.operation_json is None


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED])
@pytest.mark.parametrize("resolution", ["confirm", "reject"])
async def test_committed_resolution_replays_after_analysis_becomes_unresumable(
    resolution_case: ResolutionCase,
    status: RunStatus,
    resolution: Literal["confirm", "reject"],
) -> None:
    command: ResolveAssumption = resolution_command(resolution)
    store: SqlAlchemyClarificationStore
    async with resolution_case.stores.open() as store:
        result: DecisionResult = await store.resolve(resolution_case.decision.decision_id, command)
    await resolution_case.stop(status)
    before: ResolutionSnapshot = await snapshot(resolution_case, command.operation_id)
    async with resolution_case.stores.open() as store:
        assert await store.resolve(resolution_case.decision.decision_id, command) == result
    assert await snapshot(resolution_case, command.operation_id) == before
    assert before.extraction_status == status.value


@pytest.mark.parametrize("resolution", ["confirm", "reject"])
async def test_completed_analysis_still_allows_assumption_resolution(
    resolution_case: ResolutionCase, resolution: Literal["confirm", "reject"]
) -> None:
    store: SqlAlchemyClarificationStore
    async with resolution_case.stores.open() as store:
        await store.complete_cycle(resolution_case.run_id, 0)
    command: ResolveAssumption = resolution_command(resolution)
    async with resolution_case.stores.open() as store:
        result: DecisionResult = await store.resolve(resolution_case.decision.decision_id, command)
    after: ResolutionSnapshot = await snapshot(resolution_case, command.operation_id)
    assert result.resolution == ("confirmed" if resolution == "confirm" else "rejected")
    assert after.extraction_status == (
        RunStatus.COMPLETED if resolution == "confirm" else RunStatus.WAITING_INPUT
    )
    assert after.view.cycle == (0 if resolution == "confirm" else 1)


@dataclass(frozen=True)
class SharedResolutionCase:
    http: HttpCase
    worker: ExtractionWorker
    run_ids: tuple[UUID, UUID, UUID]
    decision: DecisionResult
    before: dict[UUID, ClarificationView]
    requests: dict[UUID, int]


async def start_shared(case: HttpCase, worker: ExtractionWorker) -> UUID:
    run: ExtractionView = await case.resources.service.start(
        ExtractionStart(
            operation_id=uuid4(),
            version_ids=[case.version.version_id],
            answer_history_mode="reuse",
            answer_history_id=(await case.service.get(case.run_id)).history_id,
        )
    )
    case.resources.runs.append(run.id)
    await worker.execute(run.id)
    return run.id


@pytest.fixture(name="shared_resolution_case")
async def shared_resolution_case_fixture(http_case: HttpCase) -> SharedResolutionCase:
    worker: ExtractionWorker = await http_case.resources.container.get(ExtractionWorker)
    cancelled_id: UUID = await start_shared(http_case, worker)
    assert (await http_case.resources.view(cancelled_id)).status == RunStatus.WAITING_INPUT
    await http_case.resources.service.cancel(cancelled_id)
    await worker.execute(cancelled_id)
    assert (await http_case.resources.view(cancelled_id)).status == RunStatus.CANCELLED
    decision: DecisionResult = await http_case.service.answer(
        http_case.run_id, http_case.question.id, answer_command(http_case, assumption=True)
    )
    await worker.execute(http_case.run_id)
    second_id: UUID = await start_shared(http_case, worker)
    assert (await http_case.resources.view(http_case.run_id)).status == RunStatus.COMPLETED
    assert (await http_case.resources.view(second_id)).status == RunStatus.COMPLETED
    run_ids: tuple[UUID, UUID, UUID] = (http_case.run_id, second_id, cancelled_id)
    before: dict[UUID, ClarificationView] = {
        run_id: await http_case.service.get(run_id) for run_id in run_ids
    }
    requests: dict[UUID, int] = {
        run_id: (await http_case.resources.view(run_id)).requests for run_id in run_ids
    }
    assert before[second_id].decisions[0].decision_id == decision.decision_id
    return SharedResolutionCase(http_case, worker, run_ids, decision, before, requests)


async def assert_reopened_bindings(case: SharedResolutionCase) -> None:
    run_id: UUID
    for run_id in case.run_ids[:2]:
        current: ClarificationView = await case.http.service.get(run_id)
        original: ClarificationView = case.before[run_id]
        assert (await case.http.resources.view(run_id)).status == RunStatus.WAITING_INPUT
        assert current.cycle == original.cycle + 1
        assert current.questions[0].revision == 2
        assert current.questions[0].status == "open"
        assert current.questions[0].sources == original.questions[0].sources
        assert current.questions[0].sources
        assert current.questions[0].requirement_ids == original.questions[0].requirement_ids
        assert current.completed_cycles == original.completed_cycles
        assert current.resume_pending
    cancelled: ClarificationView = await case.http.service.get(case.run_ids[2])
    assert (await case.http.resources.view(case.run_ids[2])).status == RunStatus.CANCELLED
    assert cancelled.questions[0].revision == case.before[case.run_ids[2]].questions[0].revision
    assert cancelled.cycle == case.before[case.run_ids[2]].cycle
    assert not cancelled.resume_pending


async def test_rejection_reopens_all_eligible_shared_runs_without_reviving_cancelled_run(
    shared_resolution_case: SharedResolutionCase,
) -> None:
    case: SharedResolutionCase = shared_resolution_case
    await case.http.service.resolve(case.decision.decision_id, resolution_command("reject"))
    await assert_reopened_bindings(case)
    await case.worker.execute(case.run_ids[1])
    reopened: ClarificationView = await case.http.service.get(case.run_ids[0])
    command: AnswerClarification = answer_command(case.http).model_copy(
        update={"expected_question_revision": reopened.questions[0].revision}
    )
    await case.http.service.answer(case.run_ids[0], reopened.questions[0].id, command)
    store: ExtractionStore
    async with case.http.resources.stores.open() as store:
        assert case.run_ids[1] in {item.id for item in await store.pending()}
    run_id: UUID
    for run_id in case.run_ids[:2]:
        await case.worker.execute(run_id)
        completed: ClarificationView = await case.http.service.get(run_id)
        assert (await case.http.resources.view(run_id)).status == RunStatus.COMPLETED
        assert [cycle.cycle for cycle in completed.completed_cycles] == [0, 1]
        assert completed.completed_cycles[0] == case.before[run_id].completed_cycles[0]
        assert (await case.http.resources.view(run_id)).requests == case.requests[run_id]
        assert completed.questions[0].sources == case.before[run_id].questions[0].sources
        assert (
            completed.questions[0].requirement_ids
            == case.before[run_id].questions[0].requirement_ids
        )
    assert (await case.http.resources.view(case.run_ids[2])).status == RunStatus.CANCELLED


async def reject_after_observing_backend(
    case: SharedResolutionCase, attempted: asyncio.Future[int]
) -> DecisionResult:
    store: SqlAlchemyClarificationStore
    async with case.http.stores.open() as store:
        backend_pid: int | None = await store.session.scalar(select(func.pg_backend_pid()))
        assert backend_pid is not None
        attempted.set_result(backend_pid)
        return await store.resolve(case.decision.decision_id, resolution_command("reject"))


async def test_shared_rejection_waits_for_linked_run_before_locking_question(
    shared_resolution_case: SharedResolutionCase,
) -> None:
    case: SharedResolutionCase = shared_resolution_case
    attempted: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    rejection: asyncio.Task[DecisionResult] | None = None
    store: SqlAlchemyClarificationStore
    try:
        async with case.http.stores.open() as store:
            await store.run(case.run_ids[1], lock=True)
            rejection = asyncio.create_task(reject_after_observing_backend(case, attempted))
            async with asyncio.timeout(3):
                await wait_for_database_lock(case.http.stores, await attempted)
                # The resolver must not own this shared question while waiting for our run.
                await store.question(case.run_ids[1], case.decision.question_id, lock=True)
                with pytest.raises(Conflict, match="stale_question_revision"):
                    await store.answer(
                        case.run_ids[1], case.decision.question_id, answer_command(case.http)
                    )
        assert rejection is not None
        async with asyncio.timeout(3):
            await rejection
    finally:
        if rejection is not None and not rejection.done():
            rejection.cancel()
            await asyncio.gather(rejection, return_exceptions=True)
    await assert_reopened_bindings(case)

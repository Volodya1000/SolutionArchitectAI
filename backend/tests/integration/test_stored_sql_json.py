from typing import Final

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.clarification_http import HttpCase, actor_client, answer_command
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import AnswerClarification
from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    ExtractionView,
)
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
    DecisionRow,
    QuestionLinkRow,
    QuestionRevisionRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("field", ["snapshot_json", "command_json"])
async def test_malformed_saved_json_is_corruption_in_bounded_summary_reads(
    http_case: HttpCase, field: str
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await http_case.resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        row: ExtractionRow | None = await session.get(ExtractionRow, http_case.run_id)
        assert row is not None
        original: str = getattr(row, field)
        setattr(row, field, "{")
    try:
        with pytest.raises(StoredExtractionCorrupt):
            await http_case.resources.service.get_status(http_case.run_id)
        with pytest.raises(StoredExtractionCorrupt):
            await http_case.resources.service.list_history(limit=100, offset=0)
        if field == "snapshot_json":
            with pytest.raises(StoredExtractionCorrupt):
                await http_case.resources.service.get_matching(
                    [http_case.version.version_id],
                    "",
                    AnswerHistorySelection(mode="reuse", history_id=http_case.run_id),
                )
    finally:
        async with sessions.begin() as session:
            row = await session.get(ExtractionRow, http_case.run_id)
            assert row is not None
            setattr(row, field, original)


@pytest.mark.parametrize(
    "saved_question",
    ["{", '{"blocking":"unknown","mandatory_conflict":null}', '{"blocking":false}'],
)
async def test_corrupt_question_blocks_only_its_run_without_breaking_pending_poll(
    http_case: HttpCase, saved_question: str
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await http_case.resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        question: QuestionRevisionRow | None = await session.get(
            QuestionRevisionRow, (http_case.question.id, http_case.question.revision)
        )
        assert question is not None
        original: str = question.snapshot_json
        question.snapshot_json = saved_question
    try:
        neighbor: ExtractionView = await http_case.resources.start(
            [http_case.version.version_id], "Independent pending run"
        )
        async with sessions.begin() as session:
            pending: list[ExtractionView] = await SqlAlchemyExtractionStore(session).pending()
        assert neighbor.id in {run.id for run in pending}
        assert http_case.run_id not in {run.id for run in pending}
        worker: ExtractionWorker = await http_case.resources.container.get(ExtractionWorker)
        await worker.execute(neighbor.id)
        assert (await http_case.resources.view(neighbor.id)).status == RunStatus.WAITING_INPUT
    finally:
        async with sessions.begin() as session:
            question = await session.get(
                QuestionRevisionRow, (http_case.question.id, http_case.question.revision)
            )
            assert question is not None
            question.snapshot_json = original


@pytest.mark.parametrize("read_path", ["get", "answer", "direct_answer"])
async def test_empty_saved_requirement_links_fail_before_answer_mutates_state(
    http_case: HttpCase,
    read_path: str,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = http_case.stores.sessions
    session: AsyncSession
    async with sessions.begin() as session:
        link: QuestionLinkRow | None = await session.get(
            QuestionLinkRow, (http_case.run_id, http_case.question.id)
        )
        assert link is not None
        original: str = link.requirement_ids_json
        link.requirement_ids_json = "[]"
    command: AnswerClarification = answer_command(http_case)
    try:
        with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
            await read_linked_question(http_case, command, read_path)
        async with sessions.begin() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DecisionRow)
                    .where(DecisionRow.run_id == http_case.run_id)
                )
                == 0
            )
            assert (
                await session.get(
                    ClarificationOperationRow,
                    (http_case.stores.actor.task_id, command.operation_id),
                )
                is None
            )
    finally:
        async with sessions.begin() as session:
            link = await session.get(QuestionLinkRow, (http_case.run_id, http_case.question.id))
            assert link is not None
            link.requirement_ids_json = original


async def read_linked_question(
    case: HttpCase, command: AnswerClarification, read_path: str
) -> None:
    if read_path == "get":
        await case.service.get(case.run_id)
    elif read_path == "answer":
        await case.service.answer(case.run_id, case.question.id, command)
    else:
        store: SqlAlchemyClarificationStore
        async with case.stores.open() as store:
            await store.answer(case.run_id, case.question.id, command)


@pytest.mark.parametrize("saved_result", ["{", "{}"])
async def test_corrupt_saved_operation_returns_typed_http_error(
    http_case: HttpCase, saved_result: str
) -> None:
    command: AnswerClarification = answer_command(http_case)
    await http_case.service.answer(http_case.run_id, http_case.question.id, command)
    session: AsyncSession
    async with http_case.stores.sessions.begin() as session:
        operation: ClarificationOperationRow | None = await session.get(
            ClarificationOperationRow, (http_case.stores.actor.task_id, command.operation_id)
        )
        assert operation is not None
        operation.result_json = saved_result
    client: httpx.AsyncClient
    async with actor_client(http_case, http_case.stores.actor) as client:
        response: httpx.Response = await client.get(
            f"/api/clarification-operations/{command.operation_id}"
        )
    assert response.status_code == 500
    assert response.json() == {"code": "stored_extraction_corrupt"}

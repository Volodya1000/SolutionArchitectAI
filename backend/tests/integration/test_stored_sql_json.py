from typing import Final

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.clarification_http import HttpCase
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    ExtractionView,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    QuestionRevisionRow,
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
    "saved_question", ["{", '{"blocking":"unknown","mandatory_conflict":null}']
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
    finally:
        async with sessions.begin() as session:
            question = await session.get(
                QuestionRevisionRow, (http_case.question.id, http_case.question.revision)
            )
            assert question is not None
            question.snapshot_json = original

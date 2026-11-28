from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import Result, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    QuestionStatus,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    QuestionLinkRow,
    QuestionRevisionRow,
)
from solution_architect_ai.persistence.stored_data import read_stored_json, read_stored_value


async def blocked_question_runs(session: AsyncSession, run_ids: list[UUID]) -> set[UUID]:
    if not run_ids:
        return set()
    rows: Result[UUID, str | None, str | None] = await session.execute(
        select(
            QuestionLinkRow.run_id, QuestionRevisionRow.snapshot_json, QuestionRevisionRow.status
        )
        .outerjoin(
            QuestionRevisionRow,
            and_(
                QuestionRevisionRow.question_id == QuestionLinkRow.question_id,
                QuestionRevisionRow.revision == QuestionLinkRow.revision,
            ),
        )
        .where(QuestionLinkRow.run_id.in_(run_ids))
    )
    return {run_id for run_id, snapshot, status in rows if stored_question_blocks(snapshot, status)}


def stored_question_blocks(snapshot: str | None, status: str | None) -> bool:
    if snapshot is None or status is None:
        return True
    try:
        question: ClarificationQuestion = read_stored_json(
            ClarificationQuestion,
            snapshot,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        question.status = read_stored_value(
            TypeAdapter(QuestionStatus),
            status,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        return question.blocks_completion
    except StoredExtractionCorrupt:
        return True

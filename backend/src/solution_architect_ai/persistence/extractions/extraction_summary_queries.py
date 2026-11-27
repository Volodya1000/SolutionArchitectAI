from uuid import UUID

from sqlalchemy import JSON, Select, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    StoredExtractionMatches,
    StoredExtractionSummary,
    StoredModelProfile,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.domain.runs import ACTIVE_STATUSES, RunStatus
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow


def extraction_summary_query() -> Select[object]:
    # Project in the database: never transfer requirements, coverage, or part result blobs.
    return select(
        func.json_build_object(
            "id",
            ExtractionRow.id,
            "status",
            ExtractionRow.status,
            "created_at",
            ExtractionRow.created_at,
            "progress",
            cast(ExtractionRow.snapshot_json, JSON)["progress"],
            "error_code",
            cast(ExtractionRow.snapshot_json, JSON)["error_code"],
            "model",
            cast(ExtractionRow.snapshot_json, JSON)["model"],
            "model_profile",
            cast(ExtractionRow.snapshot_json, JSON)["model_profile"],
            "contract_version",
            cast(ExtractionRow.snapshot_json, JSON)["contract_version"],
            "prompt_version",
            cast(ExtractionRow.snapshot_json, JSON)["prompt_version"],
            "version_ids",
            cast(ExtractionRow.command_json, JSON)["version_ids"],
            "analysis_scope",
            cast(ExtractionRow.command_json, JSON)["analysis_scope"],
        )
    )


async def get_matching_extractions(
    session: AsyncSession,
    task_id: UUID,
    version_ids: list[UUID],
    analysis_scope: str,
    profile: StoredModelProfile,
    history: AnswerHistorySelection | None = None,
) -> StoredExtractionMatches:
    if history is not None and history.mode == "new":
        return StoredExtractionMatches(active=None, current_completed=None, latest_completed=None)
    identifiers: list[str] = sorted({str(identifier) for identifier in version_ids})
    query: Select[object] = (
        extraction_summary_query()
        .where(
            ExtractionRow.task_id == task_id,
            cast(ExtractionRow.command_json, JSONB)["version_ids"].contains(identifiers),
            cast(ExtractionRow.command_json, JSONB)["version_ids"].contained_by(identifiers),
            cast(ExtractionRow.command_json, JSONB)["analysis_scope"].as_string() == analysis_scope,
        )
        .order_by(ExtractionRow.created_at.desc(), ExtractionRow.id)
        .limit(1)
    )
    if history is not None and history.history_id is not None:
        query = query.where(
            or_(
                ExtractionRow.id == history.history_id,
                cast(ExtractionRow.command_json, JSONB)["answer_history_id"].as_string()
                == str(history.history_id),
            )
        )
    else:
        query = query.where(
            cast(ExtractionRow.command_json, JSONB)["answer_history_id"].as_string().is_(None),
            or_(
                cast(ExtractionRow.command_json, JSONB)["answer_history_mode"]
                .as_string()
                .is_(None),
                cast(ExtractionRow.command_json, JSONB)["answer_history_mode"].as_string() != "new",
            ),
        )
    active: object = await session.scalar(query.where(ExtractionRow.status.in_(ACTIVE_STATUSES)))
    completed: Select[object] = query.where(ExtractionRow.status == RunStatus.COMPLETED.value)
    latest: object = await session.scalar(completed)
    current: object = await session.scalar(
        completed.where(
            cast(ExtractionRow.snapshot_json, JSONB)["model_profile"]
            == profile.model_dump(mode="json"),
            cast(ExtractionRow.snapshot_json, JSONB)["prompt_version"].as_string()
            == PROMPT_VERSION,
            cast(ExtractionRow.snapshot_json, JSONB)["contract_version"].as_string()
            == CONTRACT_VERSION,
        )
    )
    return StoredExtractionMatches(
        active=StoredExtractionSummary.model_validate(active) if active is not None else None,
        current_completed=StoredExtractionSummary.model_validate(current)
        if current is not None
        else None,
        latest_completed=StoredExtractionSummary.model_validate(latest)
        if latest is not None
        else None,
    )

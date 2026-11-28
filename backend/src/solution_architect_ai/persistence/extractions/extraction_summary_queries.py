from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
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
from solution_architect_ai.persistence.sql_json import guarded_json
from solution_architect_ai.persistence.stored_data import read_stored_model


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
            guarded_json(ExtractionRow.snapshot_json)["progress"],
            "error_code",
            guarded_json(ExtractionRow.snapshot_json)["error_code"],
            "model",
            guarded_json(ExtractionRow.snapshot_json)["model"],
            "model_profile",
            guarded_json(ExtractionRow.snapshot_json)["model_profile"],
            "contract_version",
            guarded_json(ExtractionRow.snapshot_json)["contract_version"],
            "prompt_version",
            guarded_json(ExtractionRow.snapshot_json)["prompt_version"],
            "version_ids",
            guarded_json(ExtractionRow.command_json)["version_ids"],
            "analysis_scope",
            guarded_json(ExtractionRow.command_json)["analysis_scope"],
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
            guarded_json(ExtractionRow.command_json)["version_ids"].contains(identifiers),
            guarded_json(ExtractionRow.command_json)["version_ids"].contained_by(identifiers),
            guarded_json(ExtractionRow.command_json)["analysis_scope"].as_string()
            == analysis_scope,
        )
        .order_by(ExtractionRow.created_at.desc(), ExtractionRow.id)
        .limit(1)
    )
    if history is not None and history.history_id is not None:
        query = query.where(
            or_(
                ExtractionRow.id == history.history_id,
                guarded_json(ExtractionRow.command_json)["answer_history_id"].as_string()
                == str(history.history_id),
            )
        )
    else:
        query = query.where(
            guarded_json(ExtractionRow.command_json)["answer_history_id"].as_string().is_(None),
            or_(
                guarded_json(ExtractionRow.command_json)["answer_history_mode"]
                .as_string()
                .is_(None),
                guarded_json(ExtractionRow.command_json)["answer_history_mode"].as_string()
                != "new",
            ),
        )
    active: object = await session.scalar(
        query.where(ExtractionRow.status.in_((*ACTIVE_STATUSES, RunStatus.WAITING_INPUT)))
    )
    completed: Select[object] = query.where(ExtractionRow.status == RunStatus.COMPLETED.value)
    latest: object = await session.scalar(completed)
    current: object = await session.scalar(
        completed.where(
            guarded_json(ExtractionRow.snapshot_json)["model_profile"]
            == profile.model_dump(mode="json"),
            guarded_json(ExtractionRow.snapshot_json)["prompt_version"].as_string()
            == PROMPT_VERSION,
            guarded_json(ExtractionRow.snapshot_json)["contract_version"].as_string()
            == CONTRACT_VERSION,
        )
    )
    return StoredExtractionMatches(
        active=read_stored_model(
            StoredExtractionSummary,
            active,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if active is not None
        else None,
        current_completed=read_stored_model(
            StoredExtractionSummary,
            current,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if current is not None
        else None,
        latest_completed=read_stored_model(
            StoredExtractionSummary,
            latest,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if latest is not None
        else None,
    )

from uuid import UUID

from sqlalchemy import Select, Text, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    StoredExtractionMatches,
    StoredExtractionSummary,
    StoredModelProfile,
)
from solution_architect_ai.application.prompts.extraction_pipeline import (
    current_extraction_pipeline_versions,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.domain.runs import ACTIVE_STATUSES, RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.sql_json import guarded_json
from solution_architect_ai.persistence.stored_data import read_stored_model


def saved_pipeline_versions() -> ColumnElement[object]:
    snapshot_versions: ColumnElement[object] = guarded_json(ExtractionRow.snapshot_json)[
        "pipeline_versions"
    ]
    metadata: ColumnElement[object] = guarded_json(ClarificationRunRow.metadata_json)
    legacy: ColumnElement[object] = func.jsonb_build_object(
        "extraction_prompt_version",
        guarded_json(ExtractionRow.snapshot_json)["prompt_version"],
        "extraction_contract_version",
        guarded_json(ExtractionRow.snapshot_json)["contract_version"],
        "clarification_prompt_version",
        metadata["prompt_version"],
        "clarification_contract_version",
        metadata["contract_version"],
        "clarification_review_prompt_version",
        metadata["review_prompt_version"],
        "conflict_assessment_prompt_version",
        metadata["conflict_assessment_prompt_version"],
    )
    versions: ColumnElement[object] = case(
        (or_(snapshot_versions.is_(None), func.jsonb_typeof(snapshot_versions) == "null"), legacy),
        else_=snapshot_versions,
    )
    return case(
        (
            ClarificationRunRow.metadata_json.is_not(None),
            versions.op("||")(
                func.jsonb_build_object(
                    "clarification_prompt_version",
                    metadata["prompt_version"],
                    "clarification_contract_version",
                    metadata["contract_version"],
                    "clarification_review_prompt_version",
                    metadata["review_prompt_version"],
                    "conflict_assessment_prompt_version",
                    metadata["conflict_assessment_prompt_version"],
                )
            ),
        ),
        else_=versions,
    )


def extraction_summary_query() -> Select[object]:
    # Project in the database: never transfer requirements, coverage, or part result blobs.
    return (
        select(
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
                "pipeline_versions",
                saved_pipeline_versions(),
            )
        )
        .select_from(ExtractionRow)
        .outerjoin(ClarificationRunRow, ClarificationRunRow.run_id == ExtractionRow.id)
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
    selected_history_id: UUID = (
        history.history_id if history is not None and history.history_id is not None else task_id
    )
    query = query.where(
        func.coalesce(
            cast(ClarificationRunRow.history_id, Text),
            case(
                (
                    guarded_json(ExtractionRow.command_json)["answer_history_mode"].as_string()
                    == "new",
                    cast(ExtractionRow.id, Text),
                ),
                else_=func.coalesce(
                    guarded_json(ExtractionRow.command_json)["answer_history_id"].as_string(),
                    str(task_id),
                ),
            ),
        )
        == str(selected_history_id)
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
            saved_pipeline_versions()
            == cast(current_extraction_pipeline_versions().model_dump(mode="json"), JSONB),
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

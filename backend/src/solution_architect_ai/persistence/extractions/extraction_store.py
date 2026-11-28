import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import Final
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import ScalarResult, Select, and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.agents.extraction_result_merger import (
    merge_extraction_results,
)
from solution_architect_ai.application.errors.chat_errors import Conflict, Missing
from solution_architect_ai.application.errors.document_errors import DocumentErrorCode
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    PartResult,
    RequirementView,
    SourceRef,
    StoredExtractionMatches,
    StoredExtractionSummary,
    StoredModelProfile,
)
from solution_architect_ai.application.models.structured_models import BudgetUsage
from solution_architect_ai.application.prompts.extraction_pipeline import (
    current_extraction_pipeline_versions,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.domain.requirements import CoverageWarning, EvidenceStatus
from solution_architect_ai.domain.runs import (
    ACTIVE_STATUSES,
    RunStatus,
    confirm_cancellation,
    resolve_transition,
)
from solution_architect_ai.persistence.clarifications.clarification_execution import active_elapsed
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
)
from solution_architect_ai.persistence.extractions.extraction_models import (
    ExtractionPartRow,
    ExtractionRow,
    ExtractionSourceRow,
    RequirementRow,
)
from solution_architect_ai.persistence.extractions.extraction_progress_queries import (
    read_part_progress,
)
from solution_architect_ai.persistence.extractions.extraction_question_guards import (
    blocked_question_runs,
)
from solution_architect_ai.persistence.extractions.extraction_summary_queries import (
    extraction_summary_query,
    get_matching_extractions,
)
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID
from solution_architect_ai.persistence.stored_data import (
    read_stored_json,
    read_stored_model,
    read_stored_value,
)

logger: logging.Logger = logging.getLogger(__name__)
_DOCUMENT_ERRORS: Final[frozenset[str]] = frozenset(code.value for code in DocumentErrorCode)


def extraction_view(row: ExtractionRow) -> ExtractionView:
    view: ExtractionView = read_stored_json(
        ExtractionView,
        row.snapshot_json,
        failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
    )
    command: ExtractionStart = read_stored_json(
        ExtractionStart,
        row.command_json,
        failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
    )
    view.version_ids = command.version_ids
    view.analysis_scope = command.analysis_scope
    view.requests = row.requests
    view.network_failures = row.network_failures
    view.corrections = row.corrections
    return view


class SqlAlchemyExtractionStore:
    def __init__(self, session: AsyncSession, *, task_id: UUID = DEFAULT_TASK_ID) -> None:
        self.session: AsyncSession = session
        self.task_id: UUID = task_id

    async def _get_extraction_row(self, run_id: UUID, *, lock: bool = False) -> ExtractionRow:
        query: Select[ExtractionRow] = select(ExtractionRow).where(
            ExtractionRow.id == run_id, ExtractionRow.task_id == self.task_id
        )
        row: ExtractionRow | None = await self.session.scalar(
            query.with_for_update() if lock else query
        )
        if row is None:
            raise Missing("extraction")
        return row

    async def start(
        self, command: ExtractionStart, profile: StoredModelProfile, config_digest: str
    ) -> ExtractionView:
        default_history: bool = (
            command.answer_history_mode == "reuse" and command.answer_history_id is None
        )
        payload: str = command.model_dump_json(
            exclude={"answer_history_mode", "answer_history_id"} if default_history else set()
        )
        digest: str = sha256(payload.encode()).hexdigest()
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"{self.task_id}:{command.operation_id}"},
        )
        existing: ExtractionRow | None = await self.session.scalar(
            select(ExtractionRow).where(
                ExtractionRow.task_id == self.task_id,
                ExtractionRow.operation_id == command.operation_id,
            )
        )
        if existing is not None:
            if existing.payload_digest != digest:
                raise Conflict("operation_payload_changed")
            return extraction_view(existing)
        await self._validate_answer_history(command)
        created: datetime = datetime.now(UTC)
        view: ExtractionView = ExtractionView(
            id=uuid4(),
            status=RunStatus.QUEUED,
            progress=ExtractionProgress(),
            error_code=None,
            created_at=created,
            model=profile.model,
            model_profile=profile,
            coverage=CoverageView(),
            requirements=[],
            contract_version=CONTRACT_VERSION,
            prompt_version=PROMPT_VERSION,
            version_ids=command.version_ids,
            analysis_scope=command.analysis_scope,
            pipeline_versions=current_extraction_pipeline_versions(),
        )
        self.session.add(
            ExtractionRow(
                id=view.id,
                task_id=self.task_id,
                operation_id=command.operation_id,
                payload_digest=digest,
                config_digest=config_digest,
                context_digest=None,
                command_json=payload,
                snapshot_json=view.model_dump_json(),
                status=view.status.value,
                created_at=created,
            )
        )
        await self.session.flush()
        self.session.add_all(
            ExtractionSourceRow(run_id=view.id, version_id=version)
            for version in command.version_ids
        )
        return view

    async def _validate_answer_history(self, command: ExtractionStart) -> None:
        if command.answer_history_id is None:
            return
        if command.answer_history_mode == "new":
            raise Conflict("answer_history_selection_conflict")
        if command.answer_history_id == self.task_id:
            return
        owner: UUID | None = await self.session.scalar(
            select(ClarificationRunRow.run_id)
            .join(ExtractionRow, ExtractionRow.id == ClarificationRunRow.run_id)
            .where(
                ClarificationRunRow.history_id == command.answer_history_id,
                ExtractionRow.task_id == self.task_id,
            )
            .limit(1)
        )
        if owner is None:
            raise Missing("answer_history")

    async def _describe_extraction(self, row: ExtractionRow) -> ExtractionView:
        view: ExtractionView = extraction_view(row)
        budget: ClarificationRunRow | None = await self.session.get(ClarificationRunRow, row.id)
        if view.pipeline_versions is None or (
            budget is not None and budget.metadata_json is not None
        ):
            view.pipeline_versions = (await self.get_status(row.id)).pipeline_versions
        if budget is not None:
            view.elapsed_seconds = max(view.elapsed_seconds, active_elapsed(budget))
        return view

    async def get(self, run_id: UUID) -> ExtractionView:
        return await self._describe_extraction(await self._get_extraction_row(run_id))

    async def get_operation(self, operation_id: UUID) -> ExtractionView:
        row: ExtractionRow | None = await self.session.scalar(
            select(ExtractionRow).where(
                ExtractionRow.task_id == self.task_id,
                ExtractionRow.operation_id == operation_id,
            )
        )
        if row is None:
            raise Missing("extraction_operation")
        return await self._describe_extraction(row)

    async def get_status(self, run_id: UUID) -> StoredExtractionSummary:
        metadata: object = await self.session.scalar(
            extraction_summary_query().where(
                ExtractionRow.task_id == self.task_id, ExtractionRow.id == run_id
            )
        )
        if metadata is None:
            raise Missing("extraction")
        return read_stored_model(
            StoredExtractionSummary,
            metadata,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )

    async def get_matching(
        self,
        version_ids: list[UUID],
        analysis_scope: str,
        profile: StoredModelProfile,
        history: AnswerHistorySelection | None = None,
    ) -> StoredExtractionMatches:
        return await get_matching_extractions(
            self.session, self.task_id, version_ids, analysis_scope, profile, history
        )

    async def list_history(self, *, limit: int, offset: int) -> list[StoredExtractionSummary]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid extraction history pagination")
        rows: ScalarResult[object] = await self.session.scalars(
            extraction_summary_query()
            .where(ExtractionRow.task_id == self.task_id)
            .order_by(ExtractionRow.created_at.desc(), ExtractionRow.id)
            .limit(limit + 1)
            .offset(offset)
        )
        return [
            read_stored_model(
                StoredExtractionSummary,
                row,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            for row in rows
        ]

    async def command(self, run_id: UUID) -> ExtractionStart:
        return read_stored_json(
            ExtractionStart,
            (await self._get_extraction_row(run_id)).command_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )

    async def config_digest(self, run_id: UUID) -> str:
        return (await self._get_extraction_row(run_id)).config_digest

    async def context_digest(self, run_id: UUID) -> str | None:
        return (await self._get_extraction_row(run_id)).context_digest

    async def list_runs(self) -> list[ExtractionView]:
        rows: ScalarResult[ExtractionRow] = await self.session.scalars(
            select(ExtractionRow)
            .where(ExtractionRow.task_id == self.task_id)
            .order_by(ExtractionRow.created_at.desc())
        )
        return [extraction_view(row) for row in rows]

    async def pending(self) -> list[ExtractionView]:
        rows: ScalarResult[ExtractionRow] = await self.session.scalars(
            select(ExtractionRow)
            .outerjoin(ClarificationRunRow, ClarificationRunRow.run_id == ExtractionRow.id)
            .where(
                ExtractionRow.task_id == self.task_id,
                or_(
                    ExtractionRow.status.in_(ACTIVE_STATUSES),
                    (
                        ClarificationRunRow.resume_pending.is_(True)
                        & ExtractionRow.status.in_((RunStatus.WAITING_INPUT, RunStatus.COMPLETED))
                    ),
                    and_(
                        ExtractionRow.status == RunStatus.WAITING_INPUT,
                        ClarificationRunRow.initialized.is_(True),
                    ),
                ),
            )
            .order_by(ExtractionRow.created_at)
        )
        candidates: list[ExtractionRow] = list(rows)
        blocked: set[UUID] = await blocked_question_runs(
            self.session, [row.id for row in candidates if row.status not in ACTIVE_STATUSES]
        )
        pending: list[ExtractionView] = []
        row: ExtractionRow
        for row in candidates:
            if row.id in blocked:
                continue
            try:
                pending.append(extraction_view(row))
            except StoredExtractionCorrupt:
                logger.error("extraction_snapshot_corrupt run_id=%s", row.id)
        return pending

    async def set_status(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> ExtractionView:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        view: ExtractionView = read_stored_json(
            ExtractionView,
            row.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if view.status == RunStatus.CANCELLING and status in {RunStatus.FAILED, RunStatus.RUNNING}:
            status, error = RunStatus.CANCELLED, None
        target: RunStatus = (
            confirm_cancellation(view.status)
            if status == RunStatus.CANCELLED
            else resolve_transition(view.status, status)
        )
        if not view.status.terminal:
            view.status = target
            view.error_code = error
            if target.terminal:
                view = await self._terminal_result(row, view)
                await self._finish_active_budget(run_id, view)
            row.status = target.value
            row.snapshot_json = view.model_dump_json()
        return view

    async def _finish_active_budget(self, run_id: UUID, view: ExtractionView) -> None:
        budget: ClarificationRunRow | None = await self.session.get(ClarificationRunRow, run_id)
        if budget is None:
            return
        view.elapsed_seconds = max(view.elapsed_seconds, active_elapsed(budget))
        if view.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            budget.resume_pending = False

    async def _terminal_result(self, row: ExtractionRow, view: ExtractionView) -> ExtractionView:
        try:
            view.requirements = merge_extraction_results(await self.parts(row.id))
        except StoredExtractionCorrupt:
            parts: list[PartResult] = await self._read_parts(row.id, strict=False)
            view.requirements = merge_extraction_results(parts)
            view.progress.completed_parts = len(parts)
            view.coverage.processed_fragments = len(
                {identifier for part in parts for identifier in part.fragment_ids}
            )
            view.coverage.warnings = [*view.coverage.warnings, "stored_result_corrupt"]
            view.coverage.complete = False
            view.error_code = "stored_result_corrupt"
        if view.error_code in _DOCUMENT_ERRORS:
            requirement: RequirementView
            source: SourceRef
            for requirement in view.requirements:
                for source in requirement.sources:
                    source.status = EvidenceStatus.UNVERIFIED
                    source.reason = view.error_code
        return view

    async def prepare(
        self,
        run_id: UUID,
        digest: str,
        total_parts: int,
        total_fragments: int,
        warnings: tuple[str, ...],
    ) -> None:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        if row.context_digest is not None and row.context_digest != digest:
            raise Conflict("context_changed")
        view: ExtractionView = read_stored_json(
            ExtractionView,
            row.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        view.progress.total_parts = total_parts
        view.coverage.total_fragments = total_fragments
        view.coverage.warnings = list(warnings)
        row.context_digest = digest
        row.snapshot_json = view.model_dump_json()

    async def save_part(self, run_id: UUID, part: PartResult) -> None:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        if (
            read_stored_value(
                TypeAdapter(RunStatus),
                row.status,
                strict=False,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            != RunStatus.RUNNING
        ):
            raise Conflict("extraction_not_running")
        view: ExtractionView = read_stored_json(
            ExtractionView,
            row.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if await self._read_part(run_id, part.part_id) is not None:
            return
        self.session.add(
            ExtractionPartRow(
                id=uuid4(), run_id=run_id, part_id=part.part_id, result_json=part.model_dump_json()
            )
        )
        await self.session.flush()
        view.progress.completed_parts, view.coverage.processed_fragments = await read_part_progress(
            self.session, run_id
        )
        row.snapshot_json = view.model_dump_json()

    async def get_part(self, run_id: UUID, part_id: str) -> PartResult | None:
        await self._get_extraction_row(run_id)
        return await self._read_part(run_id, part_id)

    async def _read_part(self, run_id: UUID, part_id: str) -> PartResult | None:
        payload: str | None = await self.session.scalar(
            select(ExtractionPartRow.result_json).where(
                ExtractionPartRow.run_id == run_id, ExtractionPartRow.part_id == part_id
            )
        )
        if payload is None:
            return None
        part: PartResult = read_stored_json(
            PartResult, payload, failure=StoredExtractionCorrupt("stored_result_corrupt")
        )
        if part.part_id != part_id:
            raise StoredExtractionCorrupt("stored_result_corrupt")
        return part

    async def parts(self, run_id: UUID) -> list[PartResult]:
        return await self._read_parts(run_id, strict=True)

    async def _read_parts(self, run_id: UUID, *, strict: bool) -> list[PartResult]:
        await self._get_extraction_row(run_id)
        rows: ScalarResult[ExtractionPartRow] = await self.session.scalars(
            select(ExtractionPartRow)
            .where(ExtractionPartRow.run_id == run_id)
            .order_by(ExtractionPartRow.id)
        )
        parts: list[PartResult] = []
        row: ExtractionPartRow
        for row in rows:
            try:
                parts.append(PartResult.model_validate_json(row.result_json))
            except ValidationError:
                if strict:
                    raise StoredExtractionCorrupt("stored_result_corrupt") from None
                logger.error("extraction_part_corrupt run_id=%s part_id=%s", run_id, row.part_id)
        return parts

    async def reverify_part(self, run_id: UUID, part: PartResult) -> None:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        if (
            read_stored_value(
                TypeAdapter(RunStatus),
                row.status,
                strict=False,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            == RunStatus.COMPLETED
        ):
            # A concurrent finalizer already committed the immutable result.
            return
        if (
            read_stored_value(
                TypeAdapter(RunStatus),
                row.status,
                strict=False,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            != RunStatus.RUNNING
        ):
            raise Conflict("extraction_not_running")
        stored: ExtractionPartRow | None = await self.session.scalar(
            select(ExtractionPartRow).where(
                ExtractionPartRow.run_id == run_id, ExtractionPartRow.part_id == part.part_id
            )
        )
        if stored is None:
            raise Missing("extraction_part")
        previous: PartResult = read_stored_json(
            PartResult,
            stored.result_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if [item.id for item in previous.requirements] != [item.id for item in part.requirements]:
            raise Conflict("requirement_identity_changed")
        stored.result_json = part.model_dump_json()

    async def usage(self, run_id: UUID) -> BudgetUsage:
        row: ExtractionRow = await self._get_extraction_row(run_id)
        return BudgetUsage(row.requests, row.network_failures, row.corrections)

    async def reserve(self, run_id: UUID, usage: BudgetUsage, expected_requests: int) -> None:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        if (
            read_stored_value(
                TypeAdapter(RunStatus),
                row.status,
                strict=False,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            != RunStatus.RUNNING
        ):
            raise Conflict("extraction_not_running")
        if (
            expected_requests != row.requests
            or usage.requests < row.requests
            or usage.requests > row.requests + 1
        ):
            raise Conflict("request_budget_conflict")
        row.requests, row.network_failures, row.corrections = (
            usage.requests,
            usage.network_failures,
            usage.corrections,
        )
        view: ExtractionView = read_stored_json(
            ExtractionView,
            row.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        view.requests = usage.requests
        view.network_failures = usage.network_failures
        view.corrections = usage.corrections
        row.snapshot_json = view.model_dump_json()

    async def complete(
        self, run_id: UUID, result: list[PartResult], elapsed: float, *, finalize: bool = True
    ) -> ExtractionView:
        row: ExtractionRow = await self._get_extraction_row(run_id, lock=True)
        view: ExtractionView = read_stored_json(
            ExtractionView,
            row.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if view.status.terminal or view.status == RunStatus.CANCELLING:
            return view
        if view.candidates_saved:
            return view
        if view.status != RunStatus.RUNNING:
            raise Conflict("extraction_not_running")
        if not view.progress.total_parts or len(result) != view.progress.total_parts:
            raise Conflict("incomplete_parts")
        requirements: list[RequirementView] = merge_extraction_results(result)
        self.session.add_all(
            RequirementRow(
                id=item.id,
                run_id=run_id,
                category=item.category.value,
                original_text=item.original_text,
                normalized_text=item.normalized_text,
                sources_json=json.dumps(
                    [source.model_dump(mode="json") for source in item.sources]
                ),
                review_status=item.status,
            )
            for item in requirements
        )
        view.requirements = requirements
        view.candidates_saved = True
        view.status = RunStatus.COMPLETED if finalize else RunStatus.RUNNING
        view.coverage.processed_fragments = view.coverage.total_fragments
        view.coverage.complete = all(
            item == CoverageWarning.CROSS_PART_REVIEW.value for item in view.coverage.warnings
        )
        view.elapsed_seconds = elapsed
        row.status = view.status.value
        row.snapshot_json = view.model_dump_json()
        return view

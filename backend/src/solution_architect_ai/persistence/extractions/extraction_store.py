import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import Final
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import ScalarResult, Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.agents.extraction_result_merger import (
    merge_extraction_results,
)
from solution_architect_ai.application.errors.chat_errors import Conflict, Missing
from solution_architect_ai.application.errors.document_errors import DocumentErrorCode
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    PartResult,
    RequirementView,
    SourceRef,
    StoredModelProfile,
)
from solution_architect_ai.application.models.structured_models import BudgetUsage
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
from solution_architect_ai.persistence.extractions.extraction_models import (
    ExtractionPartRow,
    ExtractionRow,
    ExtractionSourceRow,
    RequirementRow,
)
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID

logger: logging.Logger = logging.getLogger(__name__)
_DOCUMENT_ERRORS: Final[frozenset[str]] = frozenset(code.value for code in DocumentErrorCode)


def extraction_view(row: ExtractionRow) -> ExtractionView:
    view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
    command: ExtractionStart = ExtractionStart.model_validate_json(row.command_json)
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

    async def row(self, run_id: UUID, *, lock: bool = False) -> ExtractionRow:
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
        payload: str = command.model_dump_json()
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

    async def get(self, run_id: UUID) -> ExtractionView:
        return extraction_view(await self.row(run_id))

    async def command(self, run_id: UUID) -> ExtractionStart:
        return ExtractionStart.model_validate_json((await self.row(run_id)).command_json)

    async def config_digest(self, run_id: UUID) -> str:
        return (await self.row(run_id)).config_digest

    async def context_digest(self, run_id: UUID) -> str | None:
        return (await self.row(run_id)).context_digest

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
            .where(ExtractionRow.task_id == self.task_id, ExtractionRow.status.in_(ACTIVE_STATUSES))
            .order_by(ExtractionRow.created_at)
        )
        pending: list[ExtractionView] = []
        row: ExtractionRow
        for row in rows:
            try:
                pending.append(extraction_view(row))
            except ValidationError:
                logger.error("extraction_snapshot_corrupt run_id=%s", row.id)
        return pending

    async def set_status(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> ExtractionView:
        row: ExtractionRow = await self.row(run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
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
                view = await self.terminal_result(row, view)
                view.elapsed_seconds = max(0, (datetime.now(UTC) - row.created_at).total_seconds())
            row.status = target.value
            row.snapshot_json = view.model_dump_json()
        return view

    async def terminal_result(self, row: ExtractionRow, view: ExtractionView) -> ExtractionView:
        try:
            view.requirements = merge_extraction_results(await self.parts(row.id))
        except StoredExtractionCorrupt:
            parts: list[PartResult] = await self.read_parts(row.id, strict=False)
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
        row: ExtractionRow = await self.row(run_id, lock=True)
        if row.context_digest is not None and row.context_digest != digest:
            raise Conflict("context_changed")
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.progress.total_parts = total_parts
        view.coverage.total_fragments = total_fragments
        view.coverage.warnings = list(warnings)
        row.context_digest = digest
        row.snapshot_json = view.model_dump_json()

    async def save_part(self, run_id: UUID, part: PartResult) -> None:
        row: ExtractionRow = await self.row(run_id, lock=True)
        if RunStatus(row.status) != RunStatus.RUNNING:
            raise Conflict("extraction_not_running")
        existing: ExtractionPartRow | None = await self.session.scalar(
            select(ExtractionPartRow).where(
                ExtractionPartRow.run_id == run_id, ExtractionPartRow.part_id == part.part_id
            )
        )
        if existing is None:
            self.session.add(
                ExtractionPartRow(
                    id=uuid4(),
                    run_id=run_id,
                    part_id=part.part_id,
                    result_json=part.model_dump_json(),
                )
            )
            await self.session.flush()
        parts: list[PartResult] = await self.parts(run_id)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.progress.completed_parts = len(parts)
        view.coverage.processed_fragments = len(
            {fragment_id for result in parts for fragment_id in result.fragment_ids}
        )
        row.snapshot_json = view.model_dump_json()

    async def parts(self, run_id: UUID) -> list[PartResult]:
        return await self.read_parts(run_id, strict=True)

    async def read_parts(self, run_id: UUID, *, strict: bool) -> list[PartResult]:
        await self.row(run_id)
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
        row: ExtractionRow = await self.row(run_id, lock=True)
        if RunStatus(row.status) == RunStatus.COMPLETED:
            # A concurrent finalizer already committed the immutable result.
            return
        if RunStatus(row.status) != RunStatus.RUNNING:
            raise Conflict("extraction_not_running")
        stored: ExtractionPartRow | None = await self.session.scalar(
            select(ExtractionPartRow).where(
                ExtractionPartRow.run_id == run_id, ExtractionPartRow.part_id == part.part_id
            )
        )
        if stored is None:
            raise Missing("extraction_part")
        previous: PartResult = PartResult.model_validate_json(stored.result_json)
        if [item.id for item in previous.requirements] != [item.id for item in part.requirements]:
            raise Conflict("requirement_identity_changed")
        stored.result_json = part.model_dump_json()

    async def usage(self, run_id: UUID) -> BudgetUsage:
        row: ExtractionRow = await self.row(run_id)
        return BudgetUsage(row.requests, row.network_failures, row.corrections)

    async def reserve(self, run_id: UUID, usage: BudgetUsage, expected_requests: int) -> None:
        row: ExtractionRow = await self.row(run_id, lock=True)
        if RunStatus(row.status) != RunStatus.RUNNING:
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
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.requests = usage.requests
        view.network_failures = usage.network_failures
        view.corrections = usage.corrections
        row.snapshot_json = view.model_dump_json()

    async def complete(
        self, run_id: UUID, result: list[PartResult], elapsed: float
    ) -> ExtractionView:
        row: ExtractionRow = await self.row(run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        if view.status.terminal or view.status == RunStatus.CANCELLING:
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
        view.status = RunStatus.COMPLETED
        view.coverage.processed_fragments = view.coverage.total_fragments
        view.coverage.complete = all(
            item == CoverageWarning.CROSS_PART_REVIEW.value for item in view.coverage.warnings
        )
        view.elapsed_seconds = elapsed
        row.status = view.status.value
        row.snapshot_json = view.model_dump_json()
        return view

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select, update

from solution_architect_ai.application.context.mandatory_conflict_questions import (
    uncovered_conflicts,
)
from solution_architect_ai.application.errors.clarification_errors import ClarificationConflict
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import (
    ClarificationView,
    CompletedCycle,
)
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
)
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.stored_data import read_stored_json, read_stored_json_value


def active_elapsed(state: ClarificationRunRow) -> float:
    if state.active_started is None or state.heartbeat_at is None:
        return state.active_seconds
    end: datetime = min(datetime.now(UTC), state.heartbeat_at + timedelta(seconds=5))
    return state.active_seconds + max(0, (end - state.active_started).total_seconds())


class ClarificationExecution:
    def __init__(self, clarification_queries: ClarificationQueries) -> None:
        self.clarification_queries: ClarificationQueries = clarification_queries

    async def begin_segment(self, run_id: UUID) -> float:
        state: ClarificationRunRow = await self.clarification_queries.run(run_id, lock=True)
        now: datetime = datetime.now(UTC)
        if (
            state.active_started is not None
            and state.heartbeat_at is not None
            and now - state.heartbeat_at < timedelta(seconds=5)
        ):
            raise ClarificationConflict("extraction_already_running")
        state.active_started, state.heartbeat_at = now, now
        return state.active_seconds

    async def heartbeat(self, run_id: UUID, *, finish: bool = False) -> None:
        state: ClarificationRunRow = await self.clarification_queries.run(run_id, lock=True)
        now: datetime = datetime.now(UTC)
        if state.active_started is not None:
            state.active_seconds += max(0, (now - state.active_started).total_seconds())
        state.active_started = None if finish else now
        state.heartbeat_at = now

    async def set_waiting(self, run_id: UUID) -> None:
        extraction: ExtractionRow = await self.clarification_queries.extraction(run_id, lock=True)
        view: ExtractionView = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if view.status not in {RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED}:
            view.status = RunStatus.WAITING_INPUT
            extraction.status, extraction.snapshot_json = view.status.value, view.model_dump_json()

    async def complete_cycle(self, run_id: UUID, expected_cycle: int) -> None:
        state: ClarificationRunRow = await self.clarification_queries.run(run_id, lock=True)
        if state.cycle != expected_cycle:
            return
        view: ClarificationView = await self.clarification_queries.get(run_id)
        extraction: ExtractionRow = await self.clarification_queries.extraction(run_id)
        snapshot: ExtractionView = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if snapshot.status in {RunStatus.CANCELLED, RunStatus.CANCELLING, RunStatus.FAILED}:
            return
        if any(question.blocks_completion for question in view.questions) or uncovered_conflicts(
            view.conflict_assessments, view.questions
        ):
            raise ClarificationConflict("blocking_questions_open")
        if (
            view.metadata is not None
            and view.metadata.coverage is not None
            and not view.metadata.coverage.complete
        ):
            raise ClarificationConflict("clarification_review_incomplete")
        cycles: list[CompletedCycle] = read_stored_json_value(
            TypeAdapter(list[CompletedCycle]),
            state.completed_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if not any(cycle.cycle == state.cycle for cycle in cycles):
            cycles.append(
                CompletedCycle(
                    cycle=state.cycle,
                    completed_at=datetime.now(UTC),
                    decision_ids=[decision.decision_id for decision in view.decisions],
                    requirements=view.requirements,
                )
            )
            state.completed_json = TypeAdapter(list[CompletedCycle]).dump_json(cycles).decode()
        snapshot.status, snapshot.elapsed_seconds = RunStatus.COMPLETED, active_elapsed(state)
        snapshot.error_code = None
        extraction.status, extraction.snapshot_json = (
            snapshot.status.value,
            snapshot.model_dump_json(),
        )

    async def fail_continuation(self, run_id: UUID, expected_version: int, code: str) -> None:
        state: ClarificationRunRow = await self.clarification_queries.run(run_id, lock=True)
        extraction: ExtractionRow = await self.clarification_queries.extraction(run_id)
        if extraction.status != RunStatus.COMPLETED or state.resume_version != expected_version:
            return
        snapshot: ExtractionView = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        snapshot.error_code = code
        extraction.snapshot_json = snapshot.model_dump_json()
        state.resume_pending = False

    async def recover_waiting(self) -> None:
        await self.clarification_queries.session.execute(
            update(ClarificationRunRow)
            .where(
                ClarificationRunRow.run_id.in_(
                    select(ExtractionRow.id).where(
                        ExtractionRow.task_id == self.clarification_queries.actor.task_id,
                        ExtractionRow.status == RunStatus.WAITING_INPUT,
                    )
                )
            )
            .values(resume_pending=True)
        )

    async def acknowledge(self, run_id: UUID, version: int) -> None:
        state: ClarificationRunRow = await self.clarification_queries.run(run_id, lock=True)
        if state.resume_version == version:
            state.resume_pending = False

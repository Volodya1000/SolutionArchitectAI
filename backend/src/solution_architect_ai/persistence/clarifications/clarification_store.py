from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
)
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
    clarification_step_adapter,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.domain.requirements import EvidenceStatus
from solution_architect_ai.persistence.clarifications.clarification_commands import (
    ClarificationCommands,
)
from solution_architect_ai.persistence.clarifications.clarification_execution import (
    ClarificationExecution,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
    ClarificationRunRow,
    ClarificationStepRow,
)
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.stored_data import read_stored_json, read_stored_json_value


class SqlAlchemyClarificationStore(ClarificationQueries):
    async def get_resume_version(self, run_id: UUID) -> int:
        return (await self.run(run_id)).resume_version

    async def fail_continuation(self, run_id: UUID, expected_version: int, code: str) -> None:
        await ClarificationExecution(self).fail_continuation(run_id, expected_version, code)

    async def save_conflict_assessments(
        self, run_id: UUID, assessments: list[ConflictAssessment]
    ) -> None:
        state: ClarificationRunRow = await self.run(run_id, lock=True)
        if state.initialized:
            return
        extraction: ExtractionRow = await self.extraction(run_id)
        snapshot: ExtractionView = read_stored_json(
            ExtractionView,
            extraction.snapshot_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )
        if not {item.requirement_id for item in assessments} <= {
            item.id for item in snapshot.requirements
        }:
            raise StoredExtractionCorrupt("stored_extraction_corrupt")
        if any(
            item.status == "confirmed"
            and (
                not item.sources
                or any(source.status != EvidenceStatus.VERIFIED for source in item.sources)
            )
            for item in assessments
        ):
            raise StoredExtractionCorrupt("stored_extraction_corrupt")
        state.assessments_json = (
            TypeAdapter(list[ConflictAssessment]).dump_json(assessments).decode()
        )

    async def get_review_step(self, run_id: UUID, key: str) -> ClarificationStepResult | None:
        await self.extraction(run_id)
        row: ClarificationStepRow | None = await self.session.get(
            ClarificationStepRow, (run_id, key)
        )
        return (
            read_stored_json_value(
                clarification_step_adapter(),
                row.result_json,
                failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
            )
            if row is not None
            else None
        )

    async def save_review_step(
        self, run_id: UUID, key: str, result: ClarificationStepResult
    ) -> None:
        await self.extraction(run_id)
        statement: Insert = (
            insert(ClarificationStepRow)
            .values(
                run_id=run_id,
                step_key=key,
                result_json=result.model_dump_json(),
            )
            .on_conflict_do_nothing(
                index_elements=[ClarificationStepRow.run_id, ClarificationStepRow.step_key]
            )
        )
        await self.session.execute(statement)

    async def preflight_answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult | None:
        return await ClarificationCommands(self).preflight_answer(run_id, question_id, command)

    async def preflight_resume(self, run_id: UUID, command: ResumeRun) -> CommandResult | None:
        return await ClarificationCommands(self).preflight_resume(run_id, command)

    async def begin_segment(self, run_id: UUID) -> float:
        return await ClarificationExecution(self).begin_segment(run_id)

    async def heartbeat(self, run_id: UUID, *, finish: bool = False) -> None:
        await ClarificationExecution(self).heartbeat(run_id, finish=finish)

    async def set_waiting(self, run_id: UUID) -> None:
        await ClarificationExecution(self).set_waiting(run_id)

    async def complete_cycle(self, run_id: UUID, expected_cycle: int) -> None:
        await ClarificationExecution(self).complete_cycle(run_id, expected_cycle)

    async def recover_waiting(self) -> None:
        await ClarificationExecution(self).recover_waiting()

    async def acknowledge(self, run_id: UUID, version: int) -> None:
        await ClarificationExecution(self).acknowledge(run_id, version)

    async def answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult:
        return await ClarificationCommands(self).answer(run_id, question_id, command)

    async def resolve(self, decision_id: UUID, command: ResolveAssumption) -> DecisionResult:
        return await ClarificationCommands(self).resolve(decision_id, command)

    async def resume(self, run_id: UUID, command: ResumeRun) -> CommandResult:
        return await ClarificationCommands(self).resume(run_id, command)

    async def operation(self, operation_id: UUID) -> DecisionResult | CommandResult:
        row: ClarificationOperationRow | None = await self.session.get(
            ClarificationOperationRow, (self.actor.task_id, operation_id)
        )
        if row is None:
            raise Missing("operation")
        return read_stored_json_value(
            TypeAdapter(DecisionResult | CommandResult),
            row.result_json,
            failure=StoredExtractionCorrupt("stored_extraction_corrupt"),
        )

from uuid import UUID

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
)
from solution_architect_ai.persistence.clarifications.clarification_commands import (
    ClarificationCommands,
)
from solution_architect_ai.persistence.clarifications.clarification_execution import (
    ClarificationExecution,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
)
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)


class SqlAlchemyClarificationStore(ClarificationQueries):
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

    async def operation(self, operation_id: UUID) -> str:
        row: ClarificationOperationRow | None = await self.session.get(
            ClarificationOperationRow, (self.actor.task_id, operation_id)
        )
        if row is None:
            raise Missing("operation")
        return row.result_json

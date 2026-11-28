from typing import Protocol
from uuid import UUID

from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationView,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
)
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment


class ClarificationReadStore(Protocol):
    async def get(self, run_id: UUID) -> ClarificationView: ...
    async def history(self, run_id: UUID) -> list[ClarificationQuestion]: ...
    async def history_decisions(self, run_id: UUID) -> list[DecisionResult]: ...
    async def operation(self, operation_id: UUID) -> DecisionResult | CommandResult: ...


class ClarificationCommandStore(Protocol):
    async def preflight_answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult | None: ...
    async def preflight_resume(self, run_id: UUID, command: ResumeRun) -> CommandResult | None: ...
    async def answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult: ...
    async def resolve(self, decision_id: UUID, command: ResolveAssumption) -> DecisionResult: ...
    async def resume(self, run_id: UUID, command: ResumeRun) -> CommandResult: ...


class ClarificationExecutionStore(Protocol):
    async def get_resume_version(self, run_id: UUID) -> int: ...
    async def fail_continuation(self, run_id: UUID, expected_version: int, code: str) -> None: ...
    async def begin_segment(self, run_id: UUID) -> float: ...
    async def heartbeat(self, run_id: UUID, *, finish: bool = False) -> None: ...
    async def set_waiting(self, run_id: UUID) -> None: ...
    async def complete_cycle(self, run_id: UUID, expected_cycle: int) -> None: ...
    async def recover_waiting(self) -> None: ...
    async def acknowledge(self, run_id: UUID, version: int) -> None: ...


class ClarificationReviewStore(Protocol):
    async def save_conflict_assessments(
        self, run_id: UUID, assessments: list[ConflictAssessment]
    ) -> None: ...
    async def get_review_step(self, run_id: UUID, key: str) -> ClarificationStepResult | None: ...
    async def save_review_step(
        self, run_id: UUID, key: str, result: ClarificationStepResult
    ) -> None: ...
    async def set_review_metadata(self, run_id: UUID, metadata: ClarificationMetadata) -> None: ...
    async def save_questions(
        self,
        run_id: UUID,
        questions: list[ClarificationQuestion],
        metadata: ClarificationMetadata | None = None,
    ) -> None: ...


class ClarificationStore(
    ClarificationReadStore,
    ClarificationCommandStore,
    ClarificationExecutionStore,
    ClarificationReviewStore,
    Protocol,
):
    """Complete store contract assembled from focused clarification responsibilities."""

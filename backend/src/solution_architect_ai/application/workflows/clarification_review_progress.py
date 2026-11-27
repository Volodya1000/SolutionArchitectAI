from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationReviewCoverage,
)
from solution_architect_ai.application.models.structured_models import ExecutionBudget


@dataclass
class ClarificationReviewProgress:
    original: ClarificationContext
    start_requests: int
    on_progress: Callable[[ClarificationReviewCoverage], Awaitable[None]] | None
    coverage: ClarificationReviewCoverage = field(init=False)
    completed: set[int] = field(default_factory=set)
    reviewed_history: set[UUID] = field(default_factory=set)

    def __post_init__(self) -> None:
        fragments: set[str] = {str(item.fragment_id) for item in self.original.part.fragments}
        self.coverage = ClarificationReviewCoverage(
            total_fragments=len(fragments),
            total_history=len(self.original.history),
            unreviewed_fragment_ids=sorted(fragments),
            unreviewed_question_ids=[question.id for question in self.original.history],
        )

    def record(self, index: int, windows: list[ClarificationContext]) -> None:
        self.completed.add(index)
        self.reviewed_history.update(question.id for question in windows[index].payload.history)
        pending: set[str] = {
            str(fragment.fragment_id)
            for offset, context in enumerate(windows)
            if offset not in self.completed
            for fragment in context.part.fragments
        }
        self.coverage.reviewed_fragments = self.coverage.total_fragments - len(pending)
        self.coverage.unreviewed_fragment_ids = sorted(pending)
        self.coverage.reviewed_history = len(self.reviewed_history)
        self.coverage.unreviewed_question_ids = [
            question.id
            for question in self.original.history
            if question.id not in self.reviewed_history
        ]

    async def publish(self, budget: ExecutionBudget, *, complete: bool = False) -> None:
        self.coverage.complete = complete and not (
            self.coverage.unreviewed_fragment_ids or self.coverage.unreviewed_question_ids
        )
        self.coverage.model_requests = budget.requests - self.start_requests
        if self.on_progress is not None:
            await self.on_progress(self.coverage)

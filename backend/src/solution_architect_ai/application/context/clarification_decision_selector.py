from uuid import UUID

from solution_architect_ai.application.context.clarification_history_matcher import (
    ClarificationHistoryMatcher,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    DecisionResult,
)


def applicable_review_decisions(
    context: ClarificationContext, question: ClarificationQuestion
) -> list[DecisionResult]:
    matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(
        context.all_fragments or context.part.fragments, context.requirements
    )
    revisions: dict[UUID, int] = {
        previous.id: previous.revision
        for previous in context.history
        if previous.status != "open"
        and matcher.rebind(previous) is not None
        and not (question.previous_basis is not None and previous.gap_key == question.gap_key)
    }
    return [
        decision
        for decision in context.decisions
        if decision.resolution != "rejected"
        and revisions.get(decision.question_id) == decision.question_revision
    ]

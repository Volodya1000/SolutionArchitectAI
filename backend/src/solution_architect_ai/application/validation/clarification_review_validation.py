from uuid import UUID

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_decision_selector import (
    applicable_review_decisions,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.clarification_review_models import SourceReviewVerdict
from solution_architect_ai.application.validation.clarification_validation import resolve_evidence
from solution_architect_ai.domain.requirements import EvidenceStatus


def validate_source_review(
    verdict: SourceReviewVerdict, context: ClarificationContext, question: ClarificationQuestion
) -> None:
    available: set[UUID] = {
        decision.decision_id for decision in applicable_review_decisions(context, question)
    }
    if not set(verdict.answer_decision_ids) <= available:
        raise ValueError("Resolution cites an unavailable or rejected answer")
    if any(
        verify_evidence(resolve_evidence(item, context), context.part).status
        != EvidenceStatus.VERIFIED
        for item in verdict.evidence
    ):
        raise ValueError("Resolution evidence is not present in this selected source window")

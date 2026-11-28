from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.errors.structured_errors import EvidenceValidationFailure
from solution_architect_ai.application.models.clarification_agent_models import (
    ClarificationSet,
    QuestionCandidate,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.extraction_models import Evidence, SourceRef
from solution_architect_ai.domain.requirements import EvidenceStatus


def validate_clarifications(payload: ClarificationSet, context: ClarificationContext) -> None:
    candidate: QuestionCandidate
    index: int
    for index, candidate in enumerate(payload.questions):
        validate_candidate(candidate, index, context)


def validate_candidate(
    candidate: QuestionCandidate, index: int, context: ClarificationContext
) -> None:
    identifiers: set[str] = {
        context.requirement_aliases.get(identifier, identifier)
        for identifier in candidate.requirement_ids
    }
    if not identifiers <= context.requirement_ids:
        raise EvidenceValidationFailure(
            f"questions.{index}.requirement_ids", "unknown dependent requirement"
        )
    evidence: Evidence
    evidence_index: int
    for evidence_index, evidence in enumerate(candidate.evidence):
        source: SourceRef = verify_evidence(resolve_evidence(evidence, context), context.part)
        if source.status != EvidenceStatus.VERIFIED:
            raise EvidenceValidationFailure(
                f"questions.{index}.evidence.{evidence_index}",
                source.reason or "unverified evidence",
            )


def resolve_evidence(evidence: Evidence, context: ClarificationContext) -> Evidence:
    return Evidence(
        fragment_id=context.source_aliases.get(evidence.fragment_id, evidence.fragment_id),
        quote=evidence.quote,
    )

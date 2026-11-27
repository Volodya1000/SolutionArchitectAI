from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.models.clarification_agent_models import (
    ClarificationSet,
    QuestionCandidate,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.extraction_models import Evidence
from solution_architect_ai.domain.requirements import EvidenceStatus


def validate_clarifications(payload: ClarificationSet, context: ClarificationContext) -> None:
    candidate: QuestionCandidate
    for candidate in payload.questions:
        if (
            not {
                context.requirement_aliases.get(identifier, identifier)
                for identifier in candidate.requirement_ids
            }
            <= context.requirement_ids
        ):
            raise ValueError("Unknown dependent requirement")
        if any(
            verify_evidence(resolve_evidence(evidence, context), context.part).status
            != EvidenceStatus.VERIFIED
            for evidence in candidate.evidence
        ):
            raise ValueError("Unverified clarification evidence")


def resolve_evidence(evidence: Evidence, context: ClarificationContext) -> Evidence:
    return Evidence(
        fragment_id=context.source_aliases.get(evidence.fragment_id, evidence.fragment_id),
        quote=evidence.quote,
    )

from uuid import UUID, uuid4

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_history_matcher import (
    ClarificationHistoryMatcher,
)
from solution_architect_ai.application.context.source_fingerprints import (
    has_changed_clarification_basis,
    requirement_basis_fingerprint,
)
from solution_architect_ai.application.models.clarification_agent_models import QuestionCandidate
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import SourceRef
from solution_architect_ai.application.validation.clarification_validation import resolve_evidence


def canonical_gap_key(
    value: str, sources: list[SourceRef], history: tuple[ClarificationQuestion, ...]
) -> str:
    key: str = ":".join(value.casefold().split())
    if any(question.gap_key == key for question in history):
        return key
    scope: str = ",".join(
        sorted({str(source.file_id) for source in sources if source.file_id is not None})
    )
    return key if key.startswith(f"{scope}:") else f"{scope}:{key}"


def build_question(
    candidate: QuestionCandidate,
    context: ClarificationContext,
    existing: dict[str, ClarificationQuestion],
    matcher: ClarificationHistoryMatcher,
) -> ClarificationQuestion:
    sources: list[SourceRef] = [
        verify_evidence(resolve_evidence(evidence, context), context.part)
        for evidence in candidate.evidence
    ]
    key: str = canonical_gap_key(candidate.gap_key, sources, context.history)
    previous: ClarificationQuestion | None = existing.get(key)
    identifiers: list[UUID] = [
        UUID(context.requirement_aliases.get(identifier, identifier))
        for identifier in candidate.requirement_ids
    ]
    question: ClarificationQuestion = ClarificationQuestion(
        id=previous.id if previous else uuid4(),
        gap_key=key,
        text=candidate.text,
        basis=candidate.basis,
        dependent_decision=candidate.dependent_decision,
        blocking=candidate.blocking,
        requirement_ids=identifiers,
        sources=sources,
        source_fingerprints={
            source.fragment_id: matcher.source_fingerprints[source.fragment_id]
            for source in sources
        },
        requirement_fingerprints={
            UUID(
                context.requirement_aliases.get(identifier, identifier)
            ): matcher.requirement_fingerprints[
                UUID(context.requirement_aliases.get(identifier, identifier))
            ]
            for identifier in candidate.requirement_ids
        },
        requirement_basis_fingerprints={
            requirement.id: requirement_basis_fingerprint(requirement)
            for requirement in context.requirements
            if str(requirement.id)
            in {
                context.requirement_aliases.get(identifier, identifier)
                for identifier in candidate.requirement_ids
            }
        },
    )
    if previous is None:
        return question
    if (
        previous.mandatory_conflict is not None
        and previous.sources
        and {
            (source.file_id, source.version_id, source.sha256, source.fragment_id)
            for source in previous.sources
        }
        <= {
            (source.file_id, source.version_id, source.sha256, source.fragment_id)
            for source in question.sources
        }
    ):
        question.mandatory_conflict = previous.mandatory_conflict
    question.revision, question.status = previous.revision, previous.status
    if has_changed_clarification_basis(previous, question):
        question.previous_basis, question.status = previous.basis, "open"
        question.previous_sources = previous.sources
    return question

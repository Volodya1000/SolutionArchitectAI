from functools import partial
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContext,
)
from solution_architect_ai.application.context.clarification_history import (
    ClarificationHistoryMatcher,
    has_changed_source_basis,
)
from solution_architect_ai.application.models.chat_dto import DTO, Text
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import Evidence, SourceRef
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredRequest,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.requirements import EvidenceStatus


class QuestionCandidate(DTO):
    gap_key: Text
    text: Text
    basis: Text
    dependent_decision: Text
    blocking: bool
    requirement_ids: Annotated[list[str], Field(min_length=1)]
    evidence: Annotated[list[Evidence], Field(min_length=1)]
    changed_basis: bool = False


class ClarificationSet(DTO):
    questions: Annotated[list[QuestionCandidate], Field(max_length=100)]


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
    return evidence.model_copy(
        update={
            "fragment_id": context.source_aliases.get(evidence.fragment_id, evidence.fragment_id)
        }
    )


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
    question: ClarificationQuestion = ClarificationQuestion(
        id=previous.id if previous else uuid4(),
        gap_key=key,
        text=candidate.text,
        basis=candidate.basis,
        dependent_decision=candidate.dependent_decision,
        blocking=candidate.blocking,
        requirement_ids=[
            UUID(context.requirement_aliases.get(identifier, identifier))
            for identifier in candidate.requirement_ids
        ],
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
    )
    if previous is None:
        return question
    question.revision, question.status = previous.revision, previous.status
    if (
        candidate.changed_basis
        and has_changed_source_basis(previous, question)
        and {(source.version_id, source.sha256) for source in sources}
        != {(source.version_id, source.sha256) for source in previous.sources}
    ):
        question.previous_basis, question.status = previous.basis, "open"
    return question


class ClarificationAgent:
    def __init__(self, generator: StructuredOutputGenerator) -> None:
        self.generator: StructuredOutputGenerator = generator

    async def clarify(
        self, context: ClarificationContext, budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        payload: ClarificationSet = await self.generator.generate(
            StructuredRequest(context.part.messages, context.profile),
            ClarificationSet,
            budget,
            validator=partial(validate_clarifications, context=context),
        )
        questions: list[ClarificationQuestion] = []
        existing: dict[str, ClarificationQuestion] = {
            question.gap_key: question for question in context.history
        }
        matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(
            context.part.fragments, context.requirements
        )
        questions = [
            build_question(candidate, context, existing, matcher) for candidate in payload.questions
        ]
        emitted: set[UUID] = {question.id for question in questions}
        previous_question: ClarificationQuestion
        for previous_question in context.history:
            if previous_question.id in emitted or previous_question.status == "open":
                continue
            carried: ClarificationQuestion | None = matcher.rebind(previous_question)
            if carried is not None:
                questions.append(carried)
        return questions

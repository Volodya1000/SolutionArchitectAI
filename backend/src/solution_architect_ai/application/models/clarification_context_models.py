from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment, ContextPart
from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.clarification_models import (
    AssumptionDetails,
    ClarificationQuestion,
    DecisionResult,
    QuestionStatus,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import ModelProfile
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory


class ContextSource(DTO):
    fragment_id: str
    text: str


class RequirementEvidenceContext(DTO):
    fragment_id: str
    candidate_quote: str
    status: EvidenceStatus
    reason: str | None


class RequirementContext(DTO):
    id: str
    category: RequirementCategory
    original_text: str
    normalized_text: str
    fragment_ids: list[str]
    evidence: list[RequirementEvidenceContext]


class HistoricalSourceContext(DTO):
    fragment_id: str
    version_id: UUID | None
    quote: str
    status: EvidenceStatus
    reason: str | None


class QuestionHistoryContext(DTO):
    id: UUID
    gap_key: str
    revision: int
    text: str
    basis: str
    status: QuestionStatus
    requirement_ids: list[UUID]
    sources: list[HistoricalSourceContext]


class DecisionHistoryContext(DTO):
    decision_id: UUID
    question_id: UUID
    question_revision: int
    kind: Literal["answer", "assumption"]
    text: str
    basis: str
    assumption: AssumptionDetails | None
    resolution: Literal["pending", "confirmed", "rejected"]
    resolution_reason: str | None
    revision: int

    @classmethod
    def from_decision(cls, decision: DecisionResult) -> Self:
        return cls(
            decision_id=decision.decision_id,
            question_id=decision.question_id,
            question_revision=decision.question_revision,
            kind=decision.kind,
            text=decision.text,
            basis=decision.basis,
            assumption=decision.assumption,
            resolution=decision.resolution,
            resolution_reason=decision.resolution_reason,
            revision=decision.revision,
        )


class ContextCoverage(DTO):
    selected_versions: list[UUID]
    omitted_fragment_count: int = 0
    omitted_history_records: int = 0


class ClarificationPayload(DTO):
    role: Literal["clarification"] = "clarification"
    fragments: list[ContextSource]
    requirements: list[RequirementContext]
    history: list[QuestionHistoryContext]
    decisions: list[DecisionHistoryContext]
    coverage: ContextCoverage


@dataclass(frozen=True)
class ClarificationContext:
    part: ContextPart
    requirement_ids: frozenset[str]
    history: tuple[ClarificationQuestion, ...]
    profile: ModelProfile
    source_aliases: Mapping[str, str]
    requirement_aliases: Mapping[str, str]
    requirements: tuple[RequirementView, ...]
    payload: ClarificationPayload
    all_fragments: tuple[ContextFragment, ...] = ()
    decisions: tuple[DecisionResult, ...] = ()

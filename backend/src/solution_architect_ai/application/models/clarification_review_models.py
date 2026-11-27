from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from solution_architect_ai.application.models.chat_dto import DTO, Text
from solution_architect_ai.application.models.clarification_context_models import (
    ContextSource,
    DecisionHistoryContext,
    QuestionHistoryContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    ClarificationReviewCoverage,
)
from solution_architect_ai.application.models.extraction_models import Evidence


class SourceReviewSubject(DTO):
    text: str
    basis: str
    dependent_decision: str


class SourceReviewPayload(DTO):
    role: Literal["clarification_review"] = "clarification_review"
    question: SourceReviewSubject
    fragments: list[ContextSource]
    history: list[QuestionHistoryContext]
    decisions: list[DecisionHistoryContext]


class SourceReviewVerdict(DTO):
    resolved: bool
    reason: Text
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    answer_decision_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if self.resolved and not (self.evidence or self.answer_decision_ids):
            raise ValueError("A resolving condition requires source evidence or a recorded answer")
        return self


@dataclass(frozen=True)
class ClarificationReviewResult:
    questions: list[ClarificationQuestion]
    coverage: ClarificationReviewCoverage

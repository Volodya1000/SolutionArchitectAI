from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.clarification_review_models import SourceReviewVerdict
from solution_architect_ai.application.models.conflict_assessment_models import (
    ConflictAssessmentVerdict,
)


class QuestionWindowResult(DTO):
    phase: Literal["questions"] = "questions"
    questions: list[ClarificationQuestion]
    model_requests: int = Field(default=0, ge=0)


class SourceReviewWindowResult(DTO):
    phase: Literal["source_review"] = "source_review"
    verdict: SourceReviewVerdict
    model_requests: int = Field(default=0, ge=0)


class ConflictAssessmentWindowResult(DTO):
    phase: Literal["conflict_assessment"] = "conflict_assessment"
    verdict: ConflictAssessmentVerdict
    model_requests: int = Field(default=0, ge=0)


type ClarificationStepResult = Annotated[
    QuestionWindowResult | SourceReviewWindowResult | ConflictAssessmentWindowResult,
    Field(discriminator="phase"),
]


def clarification_step_adapter() -> TypeAdapter[ClarificationStepResult]:
    return TypeAdapter(ClarificationStepResult)

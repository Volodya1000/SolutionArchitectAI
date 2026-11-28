from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from solution_architect_ai.application.models.chat_dto import DTO, Text
from solution_architect_ai.application.models.extraction_models import Evidence, SourceRef


class ConflictAssessmentVerdict(DTO):
    status: Literal["candidate", "confirmed", "refuted"]
    reason: Text
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_authentic_evidence(self) -> Self:
        if self.status == "confirmed" and len({item.quote for item in self.evidence}) < 2:
            raise ValueError("Confirmed conflict requires two distinct source statements")
        if self.status == "refuted" and not self.evidence:
            raise ValueError("Refuted conflict requires a resolving source statement")
        return self


class ConflictAssessment(DTO):
    requirement_id: UUID
    status: Literal["candidate", "confirmed", "refuted"]
    reason: Text
    sources: list[SourceRef] = Field(default_factory=list)

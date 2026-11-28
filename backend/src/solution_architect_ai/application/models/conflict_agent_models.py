from typing import Literal

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.clarification_context_models import ContextSource


class ConflictAssessmentPayload(DTO):
    role: Literal["conflict_assessment"] = "conflict_assessment"
    candidate_description: str
    fragments: list[ContextSource]

from typing import Annotated

from pydantic import Field

from solution_architect_ai.application.models.chat_dto import DTO, Text
from solution_architect_ai.application.models.extraction_models import Evidence


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

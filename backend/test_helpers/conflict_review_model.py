import json

from pydantic import BaseModel

from backend.test_helpers.bounded_review_model import CrossSectionModel, RequestPayload
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.conflict_assessment_models import (
    ConflictAssessmentVerdict,
)
from solution_architect_ai.application.models.structured_models import (
    StructuredRequest,
    StructuredResponse,
)


class EstablishedConflictModel(CrossSectionModel):
    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        if _schema is not ConflictAssessmentVerdict:
            return await super().invoke(request, _schema)
        self.requests.append(request)
        self.schemas.append(_schema)
        payload: RequestPayload = RequestPayload.model_validate_json(request.messages[-1].content)
        return StructuredResponse(
            json.dumps(
                {
                    "status": "confirmed",
                    "reason": "Выявлено противоречие обязательному правилу",
                    "evidence": [
                        {"fragment_id": item.fragment_id, "quote": item.text}
                        for item in payload.fragments[-2:]
                    ],
                }
            ),
            "stop",
        )


class RefutedConflictNoQuestionsModel(CrossSectionModel):
    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        if _schema is not ClarificationSet:
            return await super().invoke(request, _schema)
        self.requests.append(request)
        self.schemas.append(_schema)
        return StructuredResponse('{"questions":[]}', "stop")

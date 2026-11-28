import json

from pydantic import BaseModel

from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationPayload,
    ContextSource,
)
from solution_architect_ai.application.models.structured_models import (
    StructuredRequest,
    StructuredResponse,
)


class RequestPayload(BaseModel):
    role: str
    fragments: list[ContextSource]


class CrossSectionModel:
    def __init__(self) -> None:
        self.requests: list[StructuredRequest] = []
        self.schemas: list[type[BaseModel]] = []

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        self.requests.append(request)
        self.schemas.append(_schema)
        payload: RequestPayload = RequestPayload.model_validate_json(request.messages[-1].content)
        if payload.role == "clarification_review":
            fragments: list[ContextSource] = payload.fragments
            answer: ContextSource | None = next(
                (fragment for fragment in fragments if "отклонить запрос" in fragment.text), None
            )
            return StructuredResponse(
                json.dumps(
                    {
                        "resolved": answer is not None,
                        "reason": "Проверены источники",
                        "evidence": [
                            {
                                "fragment_id": answer.fragment_id,
                                "quote": "При отказе отклонить запрос.",
                            }
                        ]
                        if answer
                        else [],
                    }
                ),
                "stop",
            )
        context: ClarificationPayload = ClarificationPayload.model_validate_json(
            request.messages[-1].content
        )
        source: ContextSource | None = next(
            (fragment for fragment in context.fragments if "требует уточнения" in fragment.text),
            None,
        )
        return StructuredResponse(
            json.dumps(
                {
                    "questions": [
                        {
                            "gap_key": "access:failure",
                            "text": "Как реагировать на отказ?",
                            "basis": "Реакция не указана в этом разделе",
                            "dependent_decision": "Проверка доступа",
                            "blocking": True,
                            "requirement_ids": [context.requirements[0].id],
                            "evidence": [
                                {
                                    "fragment_id": source.fragment_id,
                                    "quote": "Доступ требует уточнения.",
                                }
                            ],
                        }
                    ]
                    if source and context.requirements
                    else []
                }
            ),
            "stop",
        )

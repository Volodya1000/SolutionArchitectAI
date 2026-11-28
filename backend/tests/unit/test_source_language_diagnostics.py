import json
from time import monotonic
from typing import Final

import pytest
from pydantic import BaseModel

from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.prompts.structured_prompt import render_messages
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.source_language import validate_source_language
from solution_architect_ai.application.validation.structured_response_validator import (
    validate_response,
)
from solution_architect_ai.domain.messages import MessageRole

SOURCE: Final[str] = (
    "Система работает во внутреннем тестовом контуре и имеет обычную критичность; "
    "персональных данных нет."
)
TRANSLATION: Final[str] = (
    "The system operates in an internal test environment and has normal criticality; "
    "there is no personal data."
)


def requirement_payload(*, repaired: bool) -> str:
    return json.dumps(
        {
            "requirements": [
                {
                    "category": "system_boundary",
                    "original_text": SOURCE,
                    "normalized_text": SOURCE if repaired else TRANSLATION,
                    "evidence": [{"fragment_id": "f4", "quote": SOURCE}],
                }
            ],
            "gaps": [],
            "contradictions": [],
        }
    )


class LanguageRepairModel:
    def __init__(self) -> None:
        self.requests: list[StructuredRequest] = []
        self.wire_requests: list[tuple[StructuredMessage, ...]] = []

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        self.requests.append(request)
        self.wire_requests.append(render_messages(request, _schema))
        return StructuredResponse(requirement_payload(repaired=len(self.requests) > 1), "stop")


class CharacterCounter:
    def count(self, messages: list[MessageView]) -> int:
        return sum(len(message.content) for message in messages)


@pytest.mark.anyio
async def test_actual_qwen_translation_produces_safe_field_diagnostic_on_second_request() -> None:
    model: LanguageRepairModel = LanguageRepairModel()
    execution: ExecutionBudget = ExecutionBudget(
        max_total_requests=2,
        deadline=monotonic() + 10,
        request_timeout=5,
        network_retries=0,
        correction_retries=1,
    )
    request: StructuredRequest = StructuredRequest(
        (
            StructuredMessage(MessageRole.SYSTEM, "Extract requirements in their source language."),
            StructuredMessage(MessageRole.USER, SOURCE),
        ),
        ModelProfile("test", StructuredMode.JSON_TEXT, 16384, 2048),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model,
        GenerationPolicy(1, 60, 1, 2, 0, 14080, backoff_max=0, jitter=0),
        CharacterCounter(),
    )
    result: RequirementsExtraction = await generator.generate(
        request, RequirementsExtraction, execution
    )
    assert result.requirements[0].normalized_text == SOURCE
    assert execution.requests == 2
    assert execution.corrections == 1
    feedback: str = model.requests[1].messages[-1].content
    assert "requirements.0.normalized_text" in feedback
    assert "source language" in feedback
    assert "Cyrillic" in feedback
    assert SOURCE not in feedback
    assert TRANSLATION not in feedback
    assert model.requests[0].profile == model.requests[1].profile
    wire: tuple[StructuredMessage, ...] = model.wire_requests[1]
    assert wire[-1].role == MessageRole.USER
    assert wire[-1].content == feedback
    first_user: int = next(
        index for index, message in enumerate(wire) if message.role == MessageRole.USER
    )
    assert all(message.role != MessageRole.SYSTEM for message in wire[first_user:])


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("requirements", "original_text"),
        ("requirements", "normalized_text"),
        ("gaps", "description"),
        ("contradictions", "description"),
    ],
)
def test_wrapped_language_errors_keep_collection_index_and_field(
    collection: str,
    field: str,
) -> None:
    item: dict[str, object] = {
        "evidence": [{"fragment_id": "f0", "quote": SOURCE}]
        * (2 if collection == "contradictions" else 1),
    }
    if collection == "requirements":
        item.update(category="functional", original_text=SOURCE, normalized_text=SOURCE)
    item[field] = TRANSLATION
    payload: dict[str, object] = {"requirements": [], "gaps": [], "contradictions": []}
    payload[collection] = [item]
    raised: pytest.ExceptionInfo[StructuredGenerationFailure]
    with pytest.raises(StructuredGenerationFailure) as raised:
        validate_response(StructuredResponse(json.dumps(payload), "stop"), RequirementsExtraction)
    assert raised.value.reason == StructuredErrorCode.SCHEMA_INVALID
    diagnostic: str | None = raised.value.diagnostic
    assert diagnostic is not None
    assert f"{collection}.0.{field}" in diagnostic
    assert "Cyrillic" in diagnostic
    assert len(diagnostic) <= 200
    assert SOURCE not in diagnostic
    assert TRANSLATION not in diagnostic


def test_direct_context_language_check_preserves_latin_diagnostic_without_source_echo() -> None:
    def validate_actual_context(_value: RequirementsExtraction) -> None:
        validate_source_language(TRANSLATION, SOURCE, field_path="requirements.0.original_text")

    raised: pytest.ExceptionInfo[StructuredGenerationFailure]
    with pytest.raises(StructuredGenerationFailure) as raised:
        validate_response(
            StructuredResponse(requirement_payload(repaired=True), "stop"),
            RequirementsExtraction,
            validate_actual_context,
        )
    diagnostic: str | None = raised.value.diagnostic
    assert diagnostic is not None
    assert "requirements.0.original_text" in diagnostic
    assert "Latin" in diagnostic
    assert SOURCE not in diagnostic
    assert TRANSLATION not in diagnostic

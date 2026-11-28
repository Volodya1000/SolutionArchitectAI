import json
from functools import lru_cache
from typing import Final
from uuid import UUID

from pydantic import BaseModel

from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.structured_models import (
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.application.validation.source_message_language import (
    uses_cyrillic_source_prose,
)
from solution_architect_ai.domain.messages import MessageRole

PROMPT_VERSION: Final[str] = "structured-3"
CORRECTION_PROMPT: Final[str] = (
    "Previous response failed JSON, schema or evidence validation. Return only a complete JSON object "
    "matching the exact schema; do not invent additional source evidence."
    " Preserve the source language in all text fields. Normalization must not translate "
    "requirements, unresolved questions or contradictions."
)
_SCHEMA_PROMPT: Final[str] = (
    "Return exactly one JSON object matching this JSON Schema. "
    "Do not use Markdown fences or add prose. Schema: "
)
CORRECTION_RESERVATION: Final[str] = CORRECTION_PROMPT + " Validation diagnostic:" + " a" * 200
_CYRILLIC_GUIDANCE: Final[str] = (
    "Return only a complete JSON object, without Markdown fences or surrounding prose. "
    "Preserve the source language in human-readable fields; do not translate source prose. "
    "Keep technical names and identifiers unchanged. Copy evidence.quote as an exact, "
    "contiguous substring of the referenced fragment text, including its punctuation, "
    "case and whitespace. Copy only supplied fragment labels."
)


@lru_cache(maxsize=32)
def schema_text(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))


def render_messages(
    request: StructuredRequest,
    schema: type[BaseModel],
    *,
    reserve_corrections: int = 0,
    include_native_schema: bool = False,
) -> tuple[StructuredMessage, ...]:
    if reserve_corrections < 0:
        raise ValueError("Correction reservation must not be negative")
    prefix: tuple[StructuredMessage, ...] = ()
    if request.profile.mode == StructuredMode.JSON_TEXT or include_native_schema:
        prefix = (
            StructuredMessage(
                MessageRole.SYSTEM,
                _SCHEMA_PROMPT + schema_text(schema),
            ),
        )
    corrections: tuple[StructuredMessage, ...] = (
        StructuredMessage(MessageRole.USER, CORRECTION_RESERVATION),
    ) * reserve_corrections
    language_guidance: tuple[StructuredMessage, ...] = (
        (StructuredMessage(MessageRole.SYSTEM, _CYRILLIC_GUIDANCE),)
        if uses_cyrillic_source_prose(request.messages)
        else ()
    )
    return (*prefix, *language_guidance, *request.messages, *corrections)


def token_messages(messages: tuple[StructuredMessage, ...]) -> list[MessageView]:
    return [
        MessageView(
            id=UUID(int=0),
            role=message.role,
            content=message.content,
            position=position,
            incomplete=False,
        )
        for position, message in enumerate(messages)
    ]

import json
from functools import lru_cache
from typing import Final
from uuid import UUID

from pydantic import BaseModel

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.structured_models import (
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.domain.messages import MessageRole

CORRECTION_PROMPT: Final[str] = (
    "Previous response failed JSON or schema validation. Return only a complete JSON object "
    "matching the exact schema; do not invent additional source evidence."
)
_SCHEMA_PROMPT: Final[str] = (
    "Return exactly one JSON object matching this JSON Schema. "
    "Do not use Markdown fences or add prose. Schema: "
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
        StructuredMessage(MessageRole.USER, CORRECTION_PROMPT),
    ) * reserve_corrections
    return (*prefix, *request.messages, *corrections)


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

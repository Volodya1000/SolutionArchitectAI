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

CORRECTION_PROMPT: Final[str] = (
    "Previous response failed JSON or schema validation. Return only a complete JSON object "
    "matching the exact schema; do not invent additional source evidence."
    " Preserve the source language in all text fields. Normalization must not translate "
    "requirements, unresolved questions or contradictions."
)
_SCHEMA_PROMPT: Final[str] = (
    "Return exactly one JSON object matching this JSON Schema. "
    "Do not use Markdown fences or add prose. Schema: "
)
_CYRILLIC_GUIDANCE: Final[str] = (
    "Правила формата ответа: верни только JSON-объект, без Markdown и без тройных обратных кавычек. "
    "Первый символ ответа — {, последний — }. "
    # Intentional Russian prose complements the English structured-output contract.
    "Все человекочитаемые поля сохраняют язык процитированного исходного фрагмента. "  # noqa: RUF001
    "Если исходный фрагмент на русском, пиши формулировки, вопросы и основания на русском; "
    "названия технологий и идентификаторы не переводи. "
    "Поля original_text и normalized_text также должны оставаться на языке источника. "
    "При нормализации исправляй формулировку, но не меняй язык и смысл. "
    "Если исходная формулировка уже ясная, можно сохранить её без изменения. "
    "Поля описания пробелов и противоречий также заполняй на языке источника. "
    "Перед отправкой проверь все normalized_text: недопустимо заменять русские требования "
    "английским переводом. В evidence.quote вставляй только дословную непрерывную подстроку "  # noqa: RUF001
    "text того фрагмента, чей fragment_id указан. Не добавляй точку в конце, не меняй регистр "
    "букв, пробелы или пунктуацию. fragment_id скопируй без изменения. "
    "При необходимости цитируй весь text, включая Markdown-разметку."
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
    language_guidance: tuple[StructuredMessage, ...] = (
        (StructuredMessage(MessageRole.SYSTEM, _CYRILLIC_GUIDANCE),)
        if uses_cyrillic_source_prose(request.messages)
        else ()
    )
    return (*prefix, *request.messages, *corrections, *language_guidance)


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

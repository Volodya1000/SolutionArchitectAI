import json
from collections.abc import Iterator
from typing import Final

from solution_architect_ai.application.models.structured_models import StructuredMessage
from solution_architect_ai.application.validation.source_language import script_counts
from solution_architect_ai.domain.messages import MessageRole

_PROSE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "quote",
        "original_text",
        "normalized_text",
        "description",
        "basis",
        "answer",
        "question",
    }
)


def prose_values(value: object) -> Iterator[str]:
    nested: object
    if isinstance(value, list):
        for nested in value:
            yield from prose_values(nested)
        return
    if not isinstance(value, dict):
        return
    key: object
    for key, nested in value.items():
        if isinstance(key, str) and key in _PROSE_FIELDS and isinstance(nested, str):
            yield nested
        else:
            yield from prose_values(nested)


def message_prose(content: str) -> list[str]:
    try:
        payload: object = json.loads(content)
    except (ValueError, RecursionError):
        return []
    return list(prose_values(payload))


def uses_cyrillic_source_prose(messages: tuple[StructuredMessage, ...]) -> bool:
    """Count source prose, excluding JSON keys, IDs and English retry instructions."""
    source_texts: list[str] = []
    message: StructuredMessage
    for message in messages:
        if message.role == MessageRole.USER:
            source_texts.extend(message_prose(message.content))
    if not source_texts:
        source_texts = [message.content for message in messages if message.role == MessageRole.USER]
    cyrillic: int
    latin: int
    cyrillic, latin = script_counts(" ".join(source_texts))
    return cyrillic >= 6 and cyrillic > 2 * latin

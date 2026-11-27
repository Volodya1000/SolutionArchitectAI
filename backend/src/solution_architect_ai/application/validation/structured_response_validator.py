import json
from collections.abc import Callable
from typing import Never

from pydantic import BaseModel

from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.structured_models import StructuredResponse


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    key: str
    value: object
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate JSON key")
        values[key] = value
    return values


def reject_constant(_value: str) -> Never:
    raise ValueError("JSON numbers must be finite")


def validate_response[T: BaseModel](
    response: StructuredResponse[T], schema: type[T], validator: Callable[[T], None] | None = None
) -> T:
    if response.refused:
        raise StructuredGenerationFailure(StructuredErrorCode.REFUSAL)
    if response.finish_reason == "length":
        raise StructuredGenerationFailure(StructuredErrorCode.TRUNCATED_RESPONSE)
    if response.finish_reason != "stop":
        raise StructuredGenerationFailure(StructuredErrorCode.INVALID_RESPONSE)
    if not response.text.strip():
        raise StructuredGenerationFailure(StructuredErrorCode.EMPTY_RESPONSE)
    try:
        json.loads(response.text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise StructuredGenerationFailure(
            StructuredErrorCode.JSON_INVALID, retryable=True
        ) from None
    return validate_payload(response.text, schema, validator)


def validate_payload[T: BaseModel](
    text: str, schema: type[T], validator: Callable[[T], None] | None
) -> T:
    try:
        value: T = schema.model_validate_json(text, strict=True)
        if validator is not None:
            validator(value)
        return value
    except ValueError:
        raise StructuredGenerationFailure(
            StructuredErrorCode.SCHEMA_INVALID, retryable=True
        ) from None

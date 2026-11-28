import json
import re
from collections.abc import Callable
from typing import Never

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from solution_architect_ai.application.errors.structured_errors import (
    EvidenceValidationFailure,
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.structured_models import StructuredResponse
from solution_architect_ai.application.validation.source_language import (
    SourceLanguageValidationFailure,
)


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
    except (ValueError, RecursionError) as error:
        raise StructuredGenerationFailure(
            StructuredErrorCode.JSON_INVALID,
            retryable=True,
            diagnostic=f"$: invalid JSON ({type(error).__name__})",
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
    except ValidationError as error:
        raise StructuredGenerationFailure(
            StructuredErrorCode.SCHEMA_INVALID,
            retryable=True,
            diagnostic=schema_validation_diagnostic(error),
        ) from None
    except SourceLanguageValidationFailure as error:
        raise StructuredGenerationFailure(
            StructuredErrorCode.SCHEMA_INVALID,
            retryable=True,
            diagnostic=error.diagnostic,
        ) from None
    except EvidenceValidationFailure as error:
        raise StructuredGenerationFailure(
            StructuredErrorCode.EVIDENCE_INVALID,
            retryable=True,
            diagnostic=f"{error.field_path}: {error.reason}"[:200],
        ) from None
    except ValueError:
        raise StructuredGenerationFailure(
            StructuredErrorCode.SCHEMA_INVALID,
            retryable=True,
            diagnostic="$: application validation failed; preserve the source language",
        ) from None


def schema_validation_diagnostic(error: ValidationError) -> str:
    first: ErrorDetails = error.errors(include_input=False, include_url=False)[0]
    cause: object = first.get("ctx", {}).get("error")
    if isinstance(cause, SourceLanguageValidationFailure):
        return cause.diagnostic
    path: str = ".".join(
        str(segment) if re.fullmatch(r"[A-Za-z_0-9]+", str(segment)) else "field"
        for segment in first["loc"]
    )[:100]
    return f"{path or '$'}: {first['type']}"

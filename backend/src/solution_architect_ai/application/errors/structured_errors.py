from enum import StrEnum

from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.domain.runs import RunErrorCode


class StructuredErrorCode(StrEnum):
    CONNECTION = "connection"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    JSON_INVALID = "json_invalid"
    SCHEMA_INVALID = "schema_invalid"
    EVIDENCE_INVALID = "evidence_invalid"
    EMPTY_RESPONSE = "empty_response"
    TRUNCATED_RESPONSE = "truncated_response"
    REFUSAL = "refusal"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"
    INVALID_RESPONSE = "invalid_response"
    CONTEXT_TOO_LARGE = "context_too_large"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"


class StructuredGenerationFailure(GenerationFailure):
    def __init__(
        self,
        reason: StructuredErrorCode,
        *,
        retryable: bool = False,
        retry_after: float = 0,
        diagnostic: str | None = None,
    ) -> None:
        super().__init__(
            RunErrorCode.LLM_INVALID_RESPONSE, retryable=retryable, retry_after=retry_after
        )
        self.reason: StructuredErrorCode = reason
        self.diagnostic: str | None = diagnostic
        self.args = (reason,)


class EvidenceValidationFailure(ValueError):
    def __init__(self, field_path: str, reason: str) -> None:
        super().__init__(reason)
        self.field_path: str = field_path
        self.reason: str = reason

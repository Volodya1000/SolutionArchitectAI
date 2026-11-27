from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class SmokeModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", allow_inf_nan=False)


class AttemptReport(SmokeModel):
    response_valid: bool | None = None
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed_seconds: float = 0


class CaseReport(SmokeModel):
    name: str
    mode: str
    schema_name: str
    schema_sha256: str
    expected: str
    observed: str
    expected_outcome_observed: bool
    requests: int
    http_requests: int
    corrections: int
    network_failures: int
    received_responses: int
    valid_responses: int
    input_tokens: int | None
    output_tokens: int | None
    elapsed_seconds: float
    adapter_entered: bool
    summary: dict[str, int]
    attempts: list[AttemptReport]


class SmokeReport(SmokeModel):
    measured_at: datetime
    base_url: str
    model: str
    context_window: int
    output_limit: int
    service_tokens: int
    approximate_chars_per_token: float
    cases: list[CaseReport]
    notes: list[str]

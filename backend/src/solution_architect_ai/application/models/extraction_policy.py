from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from solution_architect_ai.application.models.structured_models import ModelProfile


@dataclass(frozen=True)
class ExtractionPolicy:
    profile: ModelProfile
    config_digest: str
    task_id: UUID
    requests: int
    deadline: float
    request_timeout: float
    network_retries: int
    validation_retries: int

    def __post_init__(self) -> None:
        if not isfinite(self.deadline) or not isfinite(self.request_timeout):
            raise ValueError("Invalid extraction policy: timeouts must be finite")
        if (
            self.requests < 1
            or self.deadline <= 0
            or self.request_timeout <= 0
            or self.network_retries < 0
            or self.validation_retries < 0
        ):
            raise ValueError("Invalid extraction policy: budgets and timeouts must be positive")

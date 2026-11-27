from uuid import uuid4

import pytest

from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.models.structured_models import ModelProfile, StructuredMode


@pytest.mark.parametrize(
    ("requests", "deadline", "timeout", "network", "validation"),
    [
        (0, 60, 10, 1, 1),
        (1, 0, 10, 1, 1),
        (1, 60, 0, 1, 1),
        (1, 60, 10, -1, 1),
        (1, 60, 10, 1, -1),
        (1, float("nan"), 10, 1, 1),
    ],
)
def test_extraction_policy_rejects_unusable_budgets(
    requests: int, deadline: float, timeout: float, network: int, validation: int
) -> None:
    with pytest.raises(ValueError, match="extraction policy"):
        ExtractionPolicy(
            ModelProfile("test", StructuredMode.JSON_TEXT, 8192, 1024),
            "digest",
            uuid4(),
            requests,
            deadline,
            timeout,
            network,
            validation,
        )

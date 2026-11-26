import pytest

from solution_architect_ai.application.generation import GenerationPolicy, retry_delay


@pytest.mark.parametrize(
    ("attempt", "retry_after", "expected"), [(0, 0, 1), (1, 0, 2), (3, 0, 2), (0, 5, 5)]
)
def test_backoff_is_capped_and_respects_server_retry_after(
    attempt: int, retry_after: float, expected: float
) -> None:
    policy: GenerationPolicy = GenerationPolicy(
        concurrency=1,
        deadline=10,
        retries=2,
        requests=3,
        backoff=1,
        input_budget=100,
        backoff_max=2,
        jitter=0,
    )
    assert retry_delay(policy, attempt, retry_after) == expected

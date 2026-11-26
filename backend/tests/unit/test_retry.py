from collections.abc import Iterator
from typing import Final

import pytest
from tenacity import AsyncRetrying

from solution_architect_ai.application.errors import GenerationFailure
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.domain.runs import RunErrorCode


@pytest.mark.anyio
async def test_retry_delays_follow_server_floor_and_capped_exponential_backoff() -> None:
    policy: GenerationPolicy = GenerationPolicy(
        concurrency=1,
        deadline=15,
        retries=3,
        requests=4,
        backoff=1,
        input_budget=100,
        backoff_max=2,
        jitter=0.125,
    )
    delays: list[float] = []
    floors: Iterator[float] = iter((0, 5, 0, 0))

    async def record(delay: float) -> None:
        delays.append(delay)

    async def retryable(error: BaseException) -> bool:
        return isinstance(error, GenerationFailure) and error.retryable

    async def unavailable() -> None:
        raise GenerationFailure(
            RunErrorCode.LLM_UNAVAILABLE, retryable=True, retry_after=next(floors)
        )

    retries: AsyncRetrying = policy.retrying(retryable).copy(sleep=record)
    with pytest.raises(GenerationFailure, match=RunErrorCode.LLM_UNAVAILABLE):
        await retries(unavailable)
    assert len(delays) == 3
    delay: float
    floor: float
    expected: Final[tuple[int, ...]] = (1, 5, 2)
    for delay, floor in zip(delays, expected, strict=True):
        assert floor <= delay <= floor + policy.jitter

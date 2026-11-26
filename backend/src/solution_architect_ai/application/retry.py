from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)
from tenacity.asyncio.retry import retry_if_exception

from solution_architect_ai.application.errors import GenerationFailure


@dataclass(frozen=True)
class GenerationPolicy:
    concurrency: int
    deadline: float
    retries: int
    requests: int
    backoff: float
    input_budget: int
    backoff_max: float = 2
    jitter: float = 0.1

    def retrying(self, predicate: Callable[[BaseException], Awaitable[bool]]) -> AsyncRetrying:
        exponential: wait_exponential = wait_exponential(
            multiplier=self.backoff, max=self.backoff_max
        )
        jitter: wait_random = wait_random(max=self.jitter)

        def wait(state: RetryCallState) -> float:
            error: BaseException | None = state.outcome.exception() if state.outcome else None
            retry_after: float = error.retry_after if isinstance(error, GenerationFailure) else 0
            return max(exponential(state), retry_after) + jitter(state)

        return AsyncRetrying(
            stop=stop_after_attempt(min(self.retries + 1, self.requests)),
            wait=wait,
            retry=retry_if_exception(predicate),
            reraise=True,
        )

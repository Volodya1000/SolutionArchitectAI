import asyncio
import json
from collections.abc import Awaitable
from dataclasses import replace
from functools import partial
from typing import Final, Never

from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying

from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.structured_models import (
    ExecutionBudget,
    StructuredMessage,
    StructuredModel,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.domain.messages import MessageRole

_CORRECTABLE: Final[frozenset[StructuredErrorCode]] = frozenset(
    {StructuredErrorCode.JSON_INVALID, StructuredErrorCode.SCHEMA_INVALID}
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


def validate_response[T: BaseModel](response: StructuredResponse[T], schema: type[T]) -> T:
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
    try:
        return schema.model_validate_json(response.text, strict=True)
    except ValidationError:
        raise StructuredGenerationFailure(
            StructuredErrorCode.SCHEMA_INVALID, retryable=True
        ) from None


async def cancellable[T](operation: Awaitable[T], cancellation: asyncio.Event | None) -> T:
    if cancellation is None:
        return await operation
    task: asyncio.Task[T] = asyncio.ensure_future(operation)
    watcher: asyncio.Task[bool] = asyncio.create_task(cancellation.wait())
    try:
        await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
        if cancellation.is_set():
            raise StructuredGenerationFailure(StructuredErrorCode.CANCELLED)
        return await task
    finally:
        task.cancel()
        watcher.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


class StructuredOutputGenerator:
    def __init__(self, adapter: StructuredModel, policy: GenerationPolicy) -> None:
        self.adapter: StructuredModel = adapter
        self.policy: GenerationPolicy = policy

    async def generate[T: BaseModel](
        self, request: StructuredRequest, schema: type[T], budget: ExecutionBudget
    ) -> T:
        budget.check()
        messages: list[StructuredMessage] = list(request.messages)
        policy: GenerationPolicy = replace(
            self.policy,
            retries=budget.network_retries + budget.correction_retries,
            requests=budget.max_total_requests,
        )
        retries: AsyncRetrying = policy.retrying(partial(self.can_retry, budget, messages))

        async def attempt() -> T:
            await budget.reserve()
            budget.check()
            response: StructuredResponse[T]
            try:
                async with asyncio.timeout(budget.request_timeout):
                    response = await self.adapter.invoke(
                        replace(request, messages=tuple(messages)), schema
                    )
            except TimeoutError:
                raise StructuredGenerationFailure(
                    StructuredErrorCode.TIMEOUT, retryable=True
                ) from None
            budget.check()
            return validate_response(response, schema)

        try:
            async with asyncio.timeout_at(budget.deadline):
                return await cancellable(retries(attempt), budget.cancellation)
        except TimeoutError:
            raise StructuredGenerationFailure(StructuredErrorCode.DEADLINE_EXCEEDED) from None

    async def can_retry(
        self, budget: ExecutionBudget, messages: list[StructuredMessage], error: BaseException
    ) -> bool:
        budget.check()
        if not isinstance(error, StructuredGenerationFailure) or not error.retryable:
            return False
        correctable: bool = error.reason in _CORRECTABLE
        remaining: int = (
            budget.correction_retries - budget.corrections
            if correctable
            else budget.network_retries - budget.network_failures
        )
        if remaining <= 0:
            return False
        if budget.requests >= budget.max_total_requests:
            raise StructuredGenerationFailure(StructuredErrorCode.BUDGET_EXHAUSTED) from None
        if correctable:
            budget.corrections += 1
            messages.append(
                StructuredMessage(
                    MessageRole.USER,
                    f"Previous response failed {error.reason}. Return only a complete JSON object "
                    "matching the exact schema; do not invent additional source evidence.",
                )
            )
        else:
            budget.network_failures += 1
        await budget.observe()
        return True

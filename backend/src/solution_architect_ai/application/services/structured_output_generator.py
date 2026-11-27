import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import partial
from typing import Final

from pydantic import BaseModel
from tenacity import AsyncRetrying

from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredMessage,
    StructuredModel,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    CORRECTION_PROMPT,
    render_messages,
    token_messages,
)
from solution_architect_ai.application.protocols.chat_protocols import TokenCounter
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.validation.structured_response_validator import (
    validate_response,
)
from solution_architect_ai.domain.messages import MessageRole

_CORRECTABLE: Final[frozenset[StructuredErrorCode]] = frozenset(
    {StructuredErrorCode.JSON_INVALID, StructuredErrorCode.SCHEMA_INVALID}
)


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
    def __init__(
        self, adapter: StructuredModel, policy: GenerationPolicy, tokens: TokenCounter
    ) -> None:
        self.adapter: StructuredModel = adapter
        self.policy: GenerationPolicy = policy
        self.tokens: TokenCounter = tokens

    async def check_context(self, request: StructuredRequest, schema: type[BaseModel]) -> None:
        rendered: tuple[StructuredMessage, ...] = render_messages(
            request, schema, include_native_schema=True
        )
        estimate: int = await asyncio.to_thread(self.tokens.count, token_messages(rendered))
        available: int = (
            request.profile.context_window
            - request.profile.output_limit
            - request.profile.service_tokens
        )
        if estimate > available:
            raise StructuredGenerationFailure(StructuredErrorCode.CONTEXT_TOO_LARGE)

    async def generate[T: BaseModel](
        self,
        request: StructuredRequest,
        schema: type[T],
        budget: ExecutionBudget,
        *,
        validator: Callable[[T], None] | None = None,
    ) -> T:
        budget.check()
        messages: list[StructuredMessage] = list(request.messages)
        policy: GenerationPolicy = replace(
            self.policy,
            retries=budget.network_retries + budget.correction_retries,
            requests=budget.max_total_requests,
        )
        retries: AsyncRetrying = policy.retrying(partial(self.can_retry, budget, messages))

        try:
            async with asyncio.timeout_at(budget.deadline):
                return await cancellable(
                    retries(
                        partial(self._invoke_once, request, schema, budget, validator, messages)
                    ),
                    budget.cancellation,
                )
        except TimeoutError:
            raise StructuredGenerationFailure(StructuredErrorCode.DEADLINE_EXCEEDED) from None

    async def _invoke_once[T: BaseModel](
        self,
        request: StructuredRequest,
        schema: type[T],
        budget: ExecutionBudget,
        validator: Callable[[T], None] | None,
        messages: list[StructuredMessage],
    ) -> T:
        current: StructuredRequest = replace(request, messages=tuple(messages))
        await self.check_context(current, schema)
        await budget.reserve()
        budget.check()
        response: StructuredResponse[T]
        try:
            async with asyncio.timeout(budget.request_timeout):
                response = await self.adapter.invoke(current, schema)
        except TimeoutError:
            raise StructuredGenerationFailure(StructuredErrorCode.TIMEOUT, retryable=True) from None
        budget.check()
        return validate_response(response, schema, validator)

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
            messages.append(StructuredMessage(MessageRole.USER, CORRECTION_PROMPT))
        else:
            budget.network_failures += 1
        await budget.observe()
        return True

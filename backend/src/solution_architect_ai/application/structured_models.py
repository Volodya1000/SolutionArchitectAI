import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

from pydantic import BaseModel

from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.domain.messages import MessageRole


class StructuredMode(StrEnum):
    NATIVE_JSON_SCHEMA = "native_json_schema"
    JSON_TEXT = "json_text"


@dataclass(frozen=True)
class StructuredMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class ModelProfile:
    name: str
    mode: StructuredMode
    context_window: int
    output_limit: int
    service_tokens: int = 0


@dataclass(frozen=True)
class StructuredRequest:
    messages: tuple[StructuredMessage, ...]
    profile: ModelProfile


@dataclass(frozen=True)
class StructuredResponse[T: BaseModel]:
    text: str
    finish_reason: str | None
    refused: bool = False
    parsed: T | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class BudgetUsage:
    requests: int
    network_failures: int
    corrections: int


@dataclass
class ExecutionBudget:
    max_total_requests: int
    deadline: float
    request_timeout: float
    network_retries: int = 1
    correction_retries: int = 1
    cancellation: asyncio.Event | None = None
    requests: int = 0
    network_failures: int = 0
    corrections: int = 0
    on_usage: Callable[[BudgetUsage], Awaitable[None]] | None = None

    def check(self) -> None:
        if self.cancellation is not None and self.cancellation.is_set():
            raise StructuredGenerationFailure(StructuredErrorCode.CANCELLED)
        if monotonic() >= self.deadline:
            raise StructuredGenerationFailure(StructuredErrorCode.DEADLINE_EXCEEDED)

    async def reserve(self) -> None:
        self.check()
        if self.requests >= self.max_total_requests:
            raise StructuredGenerationFailure(StructuredErrorCode.BUDGET_EXHAUSTED)
        self.requests += 1
        await self.observe()

    async def observe(self) -> None:
        if self.on_usage is not None:
            await self.on_usage(BudgetUsage(self.requests, self.network_failures, self.corrections))


class StructuredModel(Protocol):
    async def invoke[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResponse[T]: ...

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.pagination import AsyncPage
from openai.types import Model

from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.application.models.chat_dto import MessageView, ModelStatus
from solution_architect_ai.application.protocols.chat_protocols import Chunk
from solution_architect_ai.domain.runs import RunErrorCode
from solution_architect_ai.infrastructure.prompts import build_messages


def convert_chunk(chunk: AIMessageChunk) -> Chunk:
    reason: object = chunk.response_metadata.get("finish_reason")
    return Chunk(text=str(chunk.text), finish=reason if isinstance(reason, str) else None)


def failure(error: APIError | ValueError) -> GenerationFailure:
    if isinstance(error, APITimeoutError):
        return GenerationFailure(RunErrorCode.LLM_TIMEOUT, retryable=True)
    if isinstance(error, APIConnectionError):
        return GenerationFailure(RunErrorCode.LLM_CONNECTION, retryable=True)
    if isinstance(error, APIStatusError):
        retryable: bool = error.status_code == 429 or error.status_code >= 500
        return GenerationFailure(
            RunErrorCode.LLM_UNAVAILABLE if retryable else RunErrorCode.LLM_REJECTED,
            retryable=retryable,
            retry_after=retry_after_seconds(error.response.headers.get("retry-after", "0")),
        )
    return GenerationFailure(RunErrorCode.LLM_INVALID_RESPONSE)


def retry_after_seconds(value: str) -> float:
    try:
        seconds: float = float(value)
    except ValueError:
        return retry_after_date(value)
    return max(0, seconds) if isfinite(seconds) else 0


def retry_after_date(value: str) -> float:
    try:
        date: datetime = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        return 0
    if date.tzinfo is None:
        return 0
    return max(0, (date - datetime.now(UTC)).total_seconds())


class LangChainLLM:
    def __init__(self, model: ChatOpenAI) -> None:
        self.model: ChatOpenAI = model

    async def status(self) -> ModelStatus:
        client: object = self.model.root_async_client
        if not isinstance(client, AsyncOpenAI):
            return ModelStatus(model=self.model.model_name, available=False)
        try:
            async with asyncio.timeout(3):
                models: AsyncPage[Model] = await client.models.list()
                available: bool = any(item.id == self.model.model_name for item in models.data)
        except (APIError, TimeoutError):
            available = False
        return ModelStatus(model=self.model.model_name, available=available)

    async def chunks(self, messages: list[MessageView]) -> AsyncGenerator[Chunk]:
        try:
            upstream: AsyncIterator[AIMessageChunk] = self.model.astream(build_messages(messages))
            if not isinstance(upstream, AsyncGenerator):
                raise GenerationFailure(RunErrorCode.UNSUPPORTED_STREAM_LIFECYCLE)
            stream: AsyncIterator[AIMessageChunk]
            async with aclosing(upstream) as stream:
                chunk: AIMessageChunk
                async for chunk in stream:
                    yield convert_chunk(chunk)
        except (APIError, ValueError) as error:
            raise failure(error) from None

    @asynccontextmanager
    async def stream(self, messages: list[MessageView]) -> AsyncGenerator[AsyncIterator[Chunk]]:
        stream: AsyncGenerator[Chunk]
        async with aclosing(self.chunks(messages)) as stream:
            yield stream

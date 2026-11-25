import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI

from solution_architect_ai.application.contracts import MessageView, ModelStatus
from solution_architect_ai.application.ports import Chunk, GenerationFailure


def build_messages(messages: list[MessageView]) -> list[BaseMessage]:
    inputs: list[BaseMessage] = [
        SystemMessage(
            content="Ты помощник solution-архитектора. Отвечай по-русски, ясно и по существу. "
            "Не выдавай предположения за факты. Ответ не означает согласования архитектуры."
        )
    ]
    inputs.extend(
        HumanMessage(content=item.content)
        if item.role == "user"
        else AIMessage(content=item.content)
        for item in messages
    )
    return inputs


def convert_chunk(chunk: AIMessageChunk) -> Chunk:
    reason = chunk.response_metadata.get("finish_reason")
    return Chunk(text=str(chunk.text), finish=reason if isinstance(reason, str) else None)


def failure(error: APIError | ValueError) -> GenerationFailure:
    if isinstance(error, APITimeoutError):
        return GenerationFailure("llm_timeout", retryable=True)
    if isinstance(error, APIConnectionError):
        return GenerationFailure("llm_connection", retryable=True)
    if isinstance(error, APIStatusError):
        retryable = error.status_code == 429 or error.status_code >= 500
        return GenerationFailure(
            "llm_unavailable" if retryable else "llm_rejected",
            retryable=retryable,
            retry_after=retry_after_seconds(error.response.headers.get("retry-after", "0")),
        )
    return GenerationFailure("llm_invalid_response")


def retry_after_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        return retry_after_date(value)
    return max(0, seconds) if isfinite(seconds) else 0


def retry_after_date(value: str) -> float:
    try:
        date = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        return 0
    if date.tzinfo is None:
        return 0
    return max(0, (date - datetime.now(UTC)).total_seconds())


class LangChainLLM:
    def __init__(self, model: ChatOpenAI) -> None:
        self.model = model

    async def status(self) -> ModelStatus:
        client = self.model.root_async_client
        if not isinstance(client, AsyncOpenAI):
            return ModelStatus(model=self.model.model_name, available=False)
        try:
            async with asyncio.timeout(3):
                models = await client.models.list()
                available = any(item.id == self.model.model_name for item in models.data)
        except (APIError, TimeoutError):
            available = False
        return ModelStatus(model=self.model.model_name, available=available)

    async def chunks(self, messages: list[MessageView]) -> AsyncGenerator[Chunk]:
        try:
            upstream = self.model.astream(build_messages(messages))
            if not isinstance(upstream, AsyncGenerator):
                raise GenerationFailure("unsupported_stream_lifecycle")
            async with aclosing(upstream) as stream:
                async for chunk in stream:
                    yield convert_chunk(chunk)
        except (APIError, ValueError) as error:
            raise failure(error) from None

    @asynccontextmanager
    async def stream(self, messages: list[MessageView]) -> AsyncIterator[AsyncIterator[Chunk]]:
        async with aclosing(self.chunks(messages)) as stream:
            yield stream

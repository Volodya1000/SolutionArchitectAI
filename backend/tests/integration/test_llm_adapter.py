from collections.abc import AsyncIterator
from typing import Final, override

import httpx
import pytest
from langchain_openai import ChatOpenAI

from solution_architect_ai.application.errors import GenerationFailure
from solution_architect_ai.application.ports import Chunk
from solution_architect_ai.infrastructure.llm import LangChainLLM

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


class BrokenStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed: bool = False

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"id":"test","object":"chat.completion.chunk","created":1,"model":"test","choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
        raise httpx.RemoteProtocolError("Synthetic interrupted stream")

    @override
    async def aclose(self) -> None:
        self.closed = True


async def collect(adapter: LangChainLLM, received: list[str]) -> None:
    chunks: AsyncIterator[Chunk]
    chunk: Chunk
    async with adapter.stream([]) as chunks:
        async for chunk in chunks:
            received.append(chunk.text)


async def test_interrupted_transport_is_typed_and_closed() -> None:
    stream: BrokenStream = BrokenStream()

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            stream_usage=False,
        )
        adapter: LangChainLLM = LangChainLLM(model)
        received: list[str] = []
        error: pytest.ExceptionInfo[GenerationFailure]
        with pytest.raises(GenerationFailure) as error:
            await collect(adapter, received)
        assert received == ["partial"]
        assert error.value.retryable is True
        assert stream.closed


async def test_sdk_does_not_add_hidden_network_retries() -> None:
    requests: list[httpx.Request] = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            503, headers={"Retry-After": "3"}, json={"error": {"message": "synthetic unavailable"}}
        )

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            stream_usage=False,
        )
        error: pytest.ExceptionInfo[GenerationFailure]
        with pytest.raises(GenerationFailure) as error:
            await collect(LangChainLLM(model), [])
        assert error.value.retryable is True
        assert error.value.retry_after == 3
        assert len(requests) == 1

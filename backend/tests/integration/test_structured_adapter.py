import json
from typing import ClassVar

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict

from solution_architect_ai.application.structured import validate_response
from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.structured import LangChainStructuredModel


class Answer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    count: int


def request(mode: StructuredMode, *, name: str = "test") -> StructuredRequest:
    return StructuredRequest(
        messages=(
            StructuredMessage(MessageRole.SYSTEM, "Extract facts."),
            StructuredMessage(MessageRole.USER, "Untrusted document data."),
        ),
        profile=ModelProfile(name, mode, 4096, 512),
    )


def completion(text: str, *, finish: str = "stop") -> dict[str, object]:
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 1,
        "model": "test",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}
        ],
    }


async def validated(model: ChatOpenAI, mode: StructuredMode) -> Answer:
    response: StructuredResponse[Answer] = await LangChainStructuredModel(model).invoke(
        request(mode), Answer
    )
    return validate_response(response, Answer)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_explicit_modes_use_schema_or_json_text_and_never_tools(mode: StructuredMode) -> None:
    received: list[dict[str, object]] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        received.append(json.loads(incoming.content))
        return httpx.Response(200, json=completion('{"count":2}'))

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            stream_usage=False,
            http_socket_options=(),
        )
        response: StructuredResponse[Answer] = await LangChainStructuredModel(model).invoke(
            request(mode), Answer
        )
    assert validate_response(response, Answer).count == 2
    assert len(received) == 1
    assert "tools" not in received[0]
    assert received[0].get("stream") is False
    assert received[0].get("max_completion_tokens") == 512
    if mode == StructuredMode.NATIVE_JSON_SCHEMA:
        response_format: object = received[0]["response_format"]
        assert isinstance(response_format, dict)
        assert response_format["type"] == "json_schema"
    else:
        assert "response_format" not in received[0]
        assert "count" in str(received[0]["messages"])


@pytest.mark.anyio
async def test_rate_limit_does_not_retry_in_sdk_and_preserves_server_delay() -> None:
    requests: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
        return httpx.Response(
            429, headers={"Retry-After": "3"}, json={"error": {"message": "limit"}}
        )

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            stream_usage=False,
            http_socket_options=(),
        )
        with pytest.raises(StructuredGenerationFailure) as error:
            await LangChainStructuredModel(model).invoke(request(StructuredMode.JSON_TEXT), Answer)
    assert error.value.reason == StructuredErrorCode.RATE_LIMITED
    assert error.value.retry_after == 3
    assert len(requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
@pytest.mark.parametrize(
    ("text", "finish", "reason"),
    [
        ("not JSON", "stop", StructuredErrorCode.JSON_INVALID),
        ('{"count":"2"}', "stop", StructuredErrorCode.SCHEMA_INVALID),
        ('{"count":', "length", StructuredErrorCode.TRUNCATED_RESPONSE),
        ("", "stop", StructuredErrorCode.EMPTY_RESPONSE),
    ],
)
async def test_raw_native_and_text_errors_reach_strict_validation(
    mode: StructuredMode, text: str, finish: str, reason: StructuredErrorCode
) -> None:
    def respond(_incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion(text, finish=finish))

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            stream_usage=False,
            http_socket_options=(),
        )
        with pytest.raises(StructuredGenerationFailure) as error:
            await validated(model, mode)
    assert error.value.reason == reason


@pytest.mark.anyio
async def test_langchain_fallback_to_tools_is_rejected_before_network() -> None:
    requests: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
        return httpx.Response(200, json=completion('{"count":2}'))

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="gpt-4",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            stream_usage=False,
            http_socket_options=(),
        )
        with pytest.raises(StructuredGenerationFailure) as error:
            await LangChainStructuredModel(model).invoke(
                request(StructuredMode.NATIVE_JSON_SCHEMA, name="gpt-4"), Answer
            )
    assert error.value.reason == StructuredErrorCode.UNSUPPORTED
    assert not requests


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (400, StructuredErrorCode.UNSUPPORTED, False),
        (404, StructuredErrorCode.UNSUPPORTED, False),
        (422, StructuredErrorCode.UNSUPPORTED, False),
        (401, StructuredErrorCode.REJECTED, False),
        (403, StructuredErrorCode.REJECTED, False),
        (503, StructuredErrorCode.UNAVAILABLE, True),
    ],
)
async def test_api_errors_have_safe_typed_diagnostics(
    status: int, reason: StructuredErrorCode, retryable: bool
) -> None:
    def respond(_incoming: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "secret-prompt-content"}})

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local-test",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            stream_usage=False,
            http_socket_options=(),
        )
        with pytest.raises(StructuredGenerationFailure) as error:
            await LangChainStructuredModel(model).invoke(request(StructuredMode.JSON_TEXT), Answer)
    assert error.value.reason == reason
    assert error.value.retryable is retryable
    assert "secret-prompt-content" not in str(error.value)

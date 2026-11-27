import asyncio

import httpx
import pytest
from langchain_openai import ChatOpenAI

from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredMode,
)
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.structured import LangChainStructuredModel
from tools.structured_smoke import (
    CaseDefinition,
    SmokeAnswer,
    SmokeTrace,
    measure_case,
    validate_url,
)
from tools.structured_smoke_models import CaseReport


class ContentLengthCounter:
    def count(self, messages: list[MessageView]) -> int:
        return sum(len(message.content) for message in messages)


@pytest.mark.parametrize(
    "value",
    [
        "https://api.openai.com/v1",
        "http://192.168.0.2:1234/v1",
        "http://127.0.0.1:1234/admin",
        "http://secret@127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/v1?key=secret",
    ],
)
def test_smoke_refuses_nonlocal_or_ambiguous_endpoints(value: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        validate_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:1234/v1",
        "http://localhost:8002/v1",
        "http://[::1]:8002/v1/",
    ],
)
def test_smoke_accepts_explicit_loopback_model_endpoints(value: str) -> None:
    assert validate_url(value) == value.rstrip("/")


@pytest.mark.anyio
async def test_smoke_uses_real_generator_repairs_and_measures_wire_requests() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "invalid" if len(seen) == 1 else '{"count":2}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    trace: SmokeTrace = SmokeTrace()
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), event_hooks={"request": [trace.request]}
    ) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            http_socket_options=(),
        )
        case: CaseDefinition = CaseDefinition(
            "test",
            StructuredMode.JSON_TEXT,
            SmokeAnswer,
            (StructuredMessage(MessageRole.USER, "count=2"),),
        )
        report: CaseReport = await measure_case(
            case,
            ModelProfile("test", StructuredMode.JSON_TEXT, 4096, 512),
            trace,
            LangChainStructuredModel(model),
            ContentLengthCounter(),
        )
    assert report.observed == "validated"
    assert report.requests == report.http_requests == len(seen) == 2
    assert report.corrections == 1
    assert report.received_responses == 2
    assert report.valid_responses == 1
    assert report.input_tokens == 20
    assert report.output_tokens == 10


@pytest.mark.anyio
async def test_cancellation_probe_waits_for_adapter_entry_and_cleans_up() -> None:
    trace: SmokeTrace = SmokeTrace()

    async def respond(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), event_hooks={"request": [trace.request]}
    ) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            http_socket_options=(),
        )
        case: CaseDefinition = CaseDefinition(
            "cancel",
            StructuredMode.JSON_TEXT,
            SmokeAnswer,
            (StructuredMessage(MessageRole.USER, "count=2"),),
            expected="cancelled",
        )
        report: CaseReport = await measure_case(
            case,
            ModelProfile("test", StructuredMode.JSON_TEXT, 4096, 512),
            trace,
            LangChainStructuredModel(model),
            ContentLengthCounter(),
        )
    assert trace.entered.is_set()
    assert report.observed == "cancelled"
    assert report.requests == 1
    assert report.elapsed_seconds < 1


@pytest.mark.anyio
async def test_native_truncation_is_counted_as_received_invalid_output() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"count":'},
                        "finish_reason": "length",
                    }
                ],
            },
        )

    trace: SmokeTrace = SmokeTrace()
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), event_hooks={"request": [trace.request]}
    ) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="test",
            api_key="local",
            base_url="http://local.test/v1",
            http_async_client=client,
            max_retries=0,
            streaming=False,
            http_socket_options=(),
        )
        case: CaseDefinition = CaseDefinition(
            "truncated",
            StructuredMode.NATIVE_JSON_SCHEMA,
            SmokeAnswer,
            (StructuredMessage(MessageRole.USER, "count=2"),),
        )
        report: CaseReport = await measure_case(
            case,
            ModelProfile("test", StructuredMode.NATIVE_JSON_SCHEMA, 4096, 512),
            trace,
            LangChainStructuredModel(model),
            ContentLengthCounter(),
        )
    assert report.observed == "truncated_response"
    assert report.requests == report.http_requests == 1
    assert report.received_responses == 1
    assert report.valid_responses == 0

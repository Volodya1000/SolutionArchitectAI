import json
import warnings
from dataclasses import replace
from time import monotonic
from typing import ClassVar, Literal, Protocol, cast

import httpx
import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict

from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.prompts.clarification_prompt import (
    SYSTEM_PROMPT as CLARIFICATION_INSTRUCTIONS,
)
from solution_architect_ai.application.prompts.clarification_review_prompt import (
    SOURCE_REVIEW_PROMPT,
)
from solution_architect_ai.application.prompts.conflict_assessment_prompt import (
    CONFLICT_ASSESSMENT_PROMPT,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    SYSTEM_PROMPT as EXTRACTION_INSTRUCTIONS,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    CORRECTION_PROMPT,
    render_messages,
    token_messages,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.structured_response_validator import (
    validate_response,
)
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.structured import LangChainStructuredModel


class Answer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    count: int


class ContentLengthCounter:
    def count(self, messages: list[MessageView]) -> int:
        return sum(len(message.content) for message in messages)


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


async def validated(adapter: LangChainStructuredModel, value: StructuredRequest) -> Answer:
    response: StructuredResponse[Answer] = await adapter.invoke(value, Answer)
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
    assert received[0]["messages"] == [
        {"role": message.role.value, "content": message.content}
        for message in render_messages(request(mode), Answer)
    ]
    if mode == StructuredMode.NATIVE_JSON_SCHEMA:
        response_format: object = received[0]["response_format"]
        assert isinstance(response_format, dict)
        assert response_format["type"] == "json_schema"
    else:
        assert "response_format" not in received[0]
        assert "count" in str(received[0]["messages"])


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
@pytest.mark.parametrize(
    "instructions",
    [
        EXTRACTION_INSTRUCTIONS,
        CLARIFICATION_INSTRUCTIONS,
        SOURCE_REVIEW_PROMPT,
        CONFLICT_ASSESSMENT_PROMPT,
    ],
)
@pytest.mark.parametrize(
    "source", ["Система должна сохранять журнал аудита.", "The system shall persist the audit log."]
)
async def test_cyrillic_source_guidance_reaches_actual_adapter_messages(
    mode: StructuredMode,
    instructions: str,
    source: str,
) -> None:
    received: list[dict[str, object]] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        received.append(json.loads(incoming.content))
        return httpx.Response(200, json=completion('{"count":2}'))

    current: StructuredRequest = StructuredRequest(
        (
            StructuredMessage(MessageRole.SYSTEM, instructions),
            StructuredMessage(
                MessageRole.USER,
                json.dumps({"fragments": [{"fragment_id": "f1", "text": source}]}),
            ),
        ),
        ModelProfile("test", mode, 4096, 512),
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
        assert (await validated(LangChainStructuredModel(model), current)).count == 2

    transmitted: object = received[0]["messages"]
    assert isinstance(transmitted, list)
    guidance: object = next(
        item
        for item in transmitted
        if isinstance(item, dict)
        and item.get("role") == "system"
        and "source language" in str(item.get("content"))
    )
    assert isinstance(guidance, dict)
    assert guidance["role"] == "system"
    assert "source language" in str(guidance["content"])
    assert source not in str(guidance["content"])
    assert not any("\u0400" <= character <= "\u04ff" for character in str(guidance["content"]))
    assert all(
        not any("\u0400" <= character <= "\u04ff" for character in str(item.get("content")))
        for item in transmitted
        if isinstance(item, dict) and item.get("role") == "system"
    )
    source_message: object = next(
        item for item in transmitted if isinstance(item, dict) and item.get("role") == "user"
    )
    assert isinstance(source_message, dict)
    assert source_message["role"] == "user"
    assert source_message["content"] == current.messages[-1].content


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
            await validated(LangChainStructuredModel(model), request(mode))
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


class StructuredModelFactory(Protocol):
    def __call__(
        self,
        model: ChatOpenAI,
        schema: dict[str, object],
        *,
        method: Literal["json_schema"],
        include_raw: bool,
        strict: bool,
        max_completion_tokens: int,
    ) -> Runnable[LanguageModelInput, object]: ...


@pytest.mark.anyio
async def test_unrelated_native_warning_does_not_reject_a_supported_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original: StructuredModelFactory = cast(
        StructuredModelFactory, ChatOpenAI.with_structured_output
    )

    def with_warning(
        model: ChatOpenAI,
        schema: dict[str, object],
        *,
        method: str,
        include_raw: bool,
        strict: bool,
        max_completion_tokens: int,
    ) -> Runnable[LanguageModelInput, object]:
        assert method == "json_schema"
        warnings.warn("Unrelated library deprecation", DeprecationWarning, stacklevel=2)
        return original(
            model,
            schema,
            method="json_schema",
            include_raw=include_raw,
            strict=strict,
            max_completion_tokens=max_completion_tokens,
        )

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", with_warning)
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
            http_socket_options=(),
        )
        with pytest.warns(DeprecationWarning, match="Unrelated library deprecation"):
            assert (
                await validated(
                    LangChainStructuredModel(model), request(StructuredMode.NATIVE_JSON_SCHEMA)
                )
            ).count == 2
    assert len(received) == 1
    assert "json_schema" in str(received[0]["response_format"])
    assert "tools" not in received[0]


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


@pytest.mark.anyio
@pytest.mark.parametrize("simulate_timeout", [False, True])
async def test_transport_failures_are_typed_without_sdk_retries(simulate_timeout: bool) -> None:
    requests: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
        if simulate_timeout:
            raise httpx.ReadTimeout("synthetic", request=incoming)
        raise httpx.ConnectError("synthetic", request=incoming)

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
            await validated(LangChainStructuredModel(model), request(StructuredMode.JSON_TEXT))
    assert error.value.reason == (
        StructuredErrorCode.TIMEOUT if simulate_timeout else StructuredErrorCode.CONNECTION
    )
    assert error.value.retryable
    assert len(requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_refusal_never_becomes_an_empty_success(mode: StructuredMode) -> None:
    def respond(_incoming: httpx.Request) -> httpx.Response:
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
                        "message": {"role": "assistant", "content": None, "refusal": "declined"},
                        "finish_reason": "stop",
                    }
                ],
            },
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
            await validated(LangChainStructuredModel(model), request(mode))
    assert error.value.reason == StructuredErrorCode.REFUSAL


@pytest.mark.anyio
async def test_profile_mismatch_does_not_silently_change_model() -> None:
    requests: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
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
        with pytest.raises(StructuredGenerationFailure) as error:
            await validated(
                LangChainStructuredModel(model), request(StructuredMode.JSON_TEXT, name="other")
            )
    assert error.value.reason == StructuredErrorCode.UNSUPPORTED
    assert not requests


@pytest.mark.anyio
async def test_corrective_http_requests_never_exceed_the_context_budget() -> None:
    received: list[dict[str, object]] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        received.append(json.loads(incoming.content))
        return httpx.Response(200, json=completion("not JSON"))

    initial: StructuredRequest = request(StructuredMode.JSON_TEXT)
    feedback: str = CORRECTION_PROMPT + " Validation diagnostic: $: invalid JSON (JSONDecodeError)"
    corrected: StructuredRequest = replace(
        initial,
        messages=(*initial.messages, StructuredMessage(MessageRole.USER, feedback)),
    )
    counter: ContentLengthCounter = ContentLengthCounter()
    allowed: int = counter.count(token_messages(render_messages(corrected, Answer)))
    initial = replace(
        initial, profile=ModelProfile("test", StructuredMode.JSON_TEXT, allowed + 512 + 13, 512, 13)
    )
    execution: ExecutionBudget = ExecutionBudget(3, monotonic() + 5, 2, correction_retries=2)
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
        generator: StructuredOutputGenerator = StructuredOutputGenerator(
            LangChainStructuredModel(model),
            GenerationPolicy(1, 5, 2, 3, 0, allowed, backoff_max=0, jitter=0),
            counter,
        )
        with pytest.raises(StructuredGenerationFailure) as error:
            await generator.generate(initial, Answer, execution)
    assert error.value.reason == StructuredErrorCode.CONTEXT_TOO_LARGE
    assert len(received) == execution.requests == 2
    corrected = replace(initial, messages=corrected.messages)
    assert received[1]["messages"] == [
        {"role": message.role.value, "content": message.content}
        for message in render_messages(corrected, Answer)
    ]
    assert counter.count(token_messages(render_messages(corrected, Answer))) == allowed

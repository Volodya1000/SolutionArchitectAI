import warnings
from typing import ClassVar

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.structured_models import (
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.structured_prompt import render_messages
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.llm import retry_after_seconds


class NativeEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)
    raw: AIMessage


def structured_failure(error: APIError | ValueError) -> StructuredGenerationFailure:
    if isinstance(error, APITimeoutError):
        return StructuredGenerationFailure(StructuredErrorCode.TIMEOUT, retryable=True)
    if isinstance(error, APIConnectionError):
        return StructuredGenerationFailure(StructuredErrorCode.CONNECTION, retryable=True)
    if isinstance(error, APIStatusError):
        return status_failure(error)
    return StructuredGenerationFailure(StructuredErrorCode.UNSUPPORTED)


def status_failure(error: APIStatusError) -> StructuredGenerationFailure:
    if error.status_code == 429:
        return StructuredGenerationFailure(
            StructuredErrorCode.RATE_LIMITED,
            retryable=True,
            retry_after=retry_after_seconds(error.response.headers.get("retry-after", "0")),
        )
    if error.status_code >= 500:
        return StructuredGenerationFailure(StructuredErrorCode.UNAVAILABLE, retryable=True)
    if error.status_code in {400, 404, 422}:
        return StructuredGenerationFailure(StructuredErrorCode.UNSUPPORTED)
    return StructuredGenerationFailure(StructuredErrorCode.REJECTED)


def messages_for(request: StructuredRequest, schema: type[BaseModel]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for message in render_messages(request, schema):
        if message.role == MessageRole.SYSTEM:
            messages.append(SystemMessage(message.content))
        elif message.role == MessageRole.USER:
            messages.append(HumanMessage(message.content))
        else:
            messages.append(AIMessage(message.content))
    return messages


def response_from[T: BaseModel](raw: AIMessage, _schema: type[T]) -> StructuredResponse[T]:
    finish: object = raw.response_metadata.get("finish_reason")
    refusal: object = raw.additional_kwargs.get("refusal")
    if raw.tool_calls or raw.invalid_tool_calls:
        raise StructuredGenerationFailure(StructuredErrorCode.UNSUPPORTED)
    return StructuredResponse(
        text=raw.text,
        finish_reason=finish if isinstance(finish, str) else None,
        refused=bool(refusal),
        input_tokens=raw.usage_metadata["input_tokens"] if raw.usage_metadata else 0,
        output_tokens=raw.usage_metadata["output_tokens"] if raw.usage_metadata else 0,
    )


class LangChainStructuredModel:
    def __init__(self, model: ChatOpenAI) -> None:
        if model.max_retries != 0 or model.streaming:
            raise ValueError("Structured adapter requires max_retries=0 and streaming=False")
        self.model: ChatOpenAI = model

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResponse[T]:
        if request.profile.name != self.model.model_name:
            raise StructuredGenerationFailure(StructuredErrorCode.UNSUPPORTED)
        messages: list[BaseMessage] = messages_for(request, schema)
        try:
            if request.profile.mode == StructuredMode.NATIVE_JSON_SCHEMA:
                raw: AIMessage = await self.native(messages, schema, request.profile.output_limit)
            else:
                raw = await self.model.ainvoke(
                    messages, max_completion_tokens=request.profile.output_limit
                )
        except LengthFinishReasonError:
            raise StructuredGenerationFailure(StructuredErrorCode.TRUNCATED_RESPONSE) from None
        except ContentFilterFinishReasonError:
            raise StructuredGenerationFailure(StructuredErrorCode.REFUSAL) from None
        except (APIError, ValueError) as error:
            raise structured_failure(error) from None
        return response_from(raw, schema)

    async def native(
        self, messages: list[BaseMessage], schema: type[BaseModel], output_limit: int
    ) -> AIMessage:
        with warnings.catch_warnings(record=True) as observed:
            runnable: Runnable[LanguageModelInput, object] = self.model.with_structured_output(
                schema.model_json_schema(),
                method="json_schema",
                include_raw=True,
                strict=True,
                max_completion_tokens=output_limit,
            )
        if observed:
            raise StructuredGenerationFailure(StructuredErrorCode.UNSUPPORTED)
        result: object = await runnable.ainvoke(messages)
        try:
            return NativeEnvelope.model_validate(result).raw
        except ValidationError:
            raise StructuredGenerationFailure(StructuredErrorCode.INVALID_RESPONSE) from None

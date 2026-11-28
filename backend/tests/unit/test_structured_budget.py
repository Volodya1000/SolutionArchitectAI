from collections import deque
from dataclasses import replace
from time import monotonic
from typing import ClassVar

import pytest
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
from solution_architect_ai.application.prompts.structured_prompt import (
    CORRECTION_PROMPT,
    CORRECTION_RESERVATION,
    render_messages,
    token_messages,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.messages import MessageRole


class Answer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    count: int


class RecordedModel:
    def __init__(self, responses: tuple[str, ...] = ('{"count":2}',)) -> None:
        self.requests: list[StructuredRequest] = []
        self.wire_messages: list[tuple[StructuredMessage, ...]] = []
        self.responses: deque[str] = deque(responses)

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        self.requests.append(request)
        self.wire_messages.append(render_messages(request, _schema))
        return StructuredResponse(text=self.responses.popleft(), finish_reason="stop")


class ContentLengthCounter:
    def __init__(self) -> None:
        self.calls: list[list[MessageView]] = []

    def count(self, messages: list[MessageView]) -> int:
        self.calls.append(messages)
        return sum(len(message.content) for message in messages)


def measured_input_size(request: StructuredRequest) -> int:
    messages: tuple[StructuredMessage, ...] = render_messages(
        request, Answer, include_native_schema=True
    )
    return sum(len(message.content) for message in messages)


async def correction_trace(request: StructuredRequest) -> tuple[StructuredRequest, ...]:
    model: RecordedModel = RecordedModel(("invalid", "invalid", '{"count":2}'))
    execution: ExecutionBudget = ExecutionBudget(
        3, monotonic() + 5, 2, network_retries=0, correction_retries=2
    )
    result: Answer = await StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 4096), ContentLengthCounter()
    ).generate(request, Answer, execution)
    assert result.count == 2
    assert execution.requests == 3
    assert execution.corrections == 2
    return tuple(model.requests)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_schema_wrapper_overflow_is_rejected_before_consuming_a_request(
    mode: StructuredMode,
) -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),),
        ModelProfile("test", mode, 200, 64),
    )
    execution: ExecutionBudget = ExecutionBudget(3, monotonic() + 5, 2)
    model: RecordedModel = RecordedModel()
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 136), ContentLengthCounter()
    )
    with pytest.raises(StructuredGenerationFailure) as error:
        await generator.generate(request, Answer, execution)
    assert error.value.reason == StructuredErrorCode.CONTEXT_TOO_LARGE
    assert execution.requests == 0
    assert not model.requests


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_service_reserve_is_deducted_before_a_network_request(mode: StructuredMode) -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),), ModelProfile("test", mode, 4096, 64)
    )
    counter: ContentLengthCounter = ContentLengthCounter()
    size: int = counter.count(
        token_messages(render_messages(request, Answer, include_native_schema=True))
    )
    request = replace(request, profile=ModelProfile("test", mode, size + 64 + 17 - 1, 64, 17))
    model: RecordedModel = RecordedModel()
    execution: ExecutionBudget = ExecutionBudget(3, monotonic() + 5, 2)
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 4096), counter
    )
    with pytest.raises(StructuredGenerationFailure) as error:
        await generator.generate(request, Answer, execution)
    assert error.value.reason == StructuredErrorCode.CONTEXT_TOO_LARGE
    assert execution.requests == 0
    assert not model.requests


@pytest.mark.anyio
async def test_second_correction_overflow_never_reserves_or_sends_a_third_request() -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),),
        ModelProfile("test", StructuredMode.JSON_TEXT, 4096, 64),
    )
    counter: ContentLengthCounter = ContentLengthCounter()
    attempts: tuple[StructuredRequest, ...] = await correction_trace(request)
    one_correction: int = measured_input_size(attempts[1])
    assert measured_input_size(attempts[2]) > one_correction
    request = replace(
        request,
        profile=ModelProfile("test", StructuredMode.JSON_TEXT, one_correction + 64 + 17, 64, 17),
    )
    model: RecordedModel = RecordedModel(("invalid", "invalid", '{"count":2}'))
    execution: ExecutionBudget = ExecutionBudget(3, monotonic() + 5, 2, correction_retries=2)
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 4096), counter
    )
    with pytest.raises(StructuredGenerationFailure) as error:
        await generator.generate(request, Answer, execution)
    assert error.value.reason == StructuredErrorCode.CONTEXT_TOO_LARGE
    assert execution.requests == 2
    assert len(model.requests) == 2
    assert measured_input_size(model.requests[1]) == one_correction
    assert sum(len(message.content) for message in counter.calls[-1]) > one_correction
    feedback: StructuredMessage = model.requests[1].messages[-1]
    assert feedback.role == MessageRole.USER
    assert feedback.content.startswith(CORRECTION_PROMPT)
    assert "Validation diagnostic:" in feedback.content
    assert "invalid JSON" in feedback.content
    assert list(model.responses) == ['{"count":2}']


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_reserving_all_corrections_covers_the_last_real_attempt(
    mode: StructuredMode,
) -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),), ModelProfile("test", mode, 4096, 64)
    )
    counter: ContentLengthCounter = ContentLengthCounter()
    reserved: int = counter.count(
        token_messages(
            render_messages(request, Answer, reserve_corrections=2, include_native_schema=True)
        )
    )
    request = replace(request, profile=ModelProfile("test", mode, reserved + 64 + 17, 64, 17))
    model: RecordedModel = RecordedModel(("invalid", "invalid", '{"count":2}'))
    execution: ExecutionBudget = ExecutionBudget(3, monotonic() + 5, 2, correction_retries=2)
    result: Answer = await StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 4096), counter
    ).generate(request, Answer, execution)
    assert result.count == 2
    assert execution.requests == 3
    assert len(model.requests) == 3
    assert all(measured_input_size(attempt) <= reserved for attempt in model.requests)
    assert sum(len(message.content) for message in counter.calls[-1]) <= reserved
    assert all(
        message.content != CORRECTION_RESERVATION
        for messages in model.wire_messages
        for message in messages
    )


@pytest.mark.anyio
@pytest.mark.parametrize("mode", list(StructuredMode))
async def test_last_real_correction_fits_the_context_boundary_exactly(mode: StructuredMode) -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),), ModelProfile("test", mode, 4096, 64)
    )
    attempts: tuple[StructuredRequest, ...] = await correction_trace(request)
    final_size: int = measured_input_size(attempts[-1])
    request = replace(request, profile=ModelProfile("test", mode, final_size + 64 + 17, 64, 17))
    model: RecordedModel = RecordedModel(("invalid", "invalid", '{"count":2}'))
    execution: ExecutionBudget = ExecutionBudget(
        3, monotonic() + 5, 2, network_retries=0, correction_retries=2
    )
    result: Answer = await StructuredOutputGenerator(
        model, GenerationPolicy(1, 5, 2, 3, 0, 4096), ContentLengthCounter()
    ).generate(request, Answer, execution)
    assert result.count == 2
    assert execution.requests == 3
    assert execution.corrections == 2
    assert len(model.requests) == 3
    assert all(measured_input_size(attempt) <= final_size for attempt in model.requests)
    assert measured_input_size(model.requests[-1]) == final_size


def test_native_schema_is_only_inserted_for_conservative_budget_estimation() -> None:
    request: StructuredRequest = StructuredRequest(
        (StructuredMessage(MessageRole.USER, "Read."),),
        ModelProfile("test", StructuredMode.NATIVE_JSON_SCHEMA, 4096, 64),
    )
    assert render_messages(request, Answer) == request.messages
    estimated: tuple[StructuredMessage, ...] = render_messages(
        request, Answer, include_native_schema=True, reserve_corrections=2
    )
    assert estimated[0].role == MessageRole.SYSTEM
    assert estimated[1] == request.messages[0]
    assert [item.content for item in estimated[-2:]] == [
        CORRECTION_RESERVATION,
        CORRECTION_RESERVATION,
    ]

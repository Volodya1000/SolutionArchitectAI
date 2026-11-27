import asyncio
from collections import deque
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
    BudgetUsage,
    ExecutionBudget,
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.structured_response_validator import (
    validate_response,
)
from solution_architect_ai.domain.messages import MessageRole


class Answer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    count: int


class ContentLengthCounter:
    def count(self, messages: list[MessageView]) -> int:
        return sum(len(message.content) for message in messages)


class ScriptedModel:
    def __init__(
        self, responses: list[str | StructuredGenerationFailure], pause: float = 0
    ) -> None:
        self.responses: deque[str | StructuredGenerationFailure] = deque(responses)
        self.requests: list[StructuredRequest] = []
        self.pause: float = pause
        self.started: asyncio.Event = asyncio.Event()
        self.closed: bool = False

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        self.requests.append(request)
        self.started.set()
        try:
            if self.pause:
                await asyncio.sleep(self.pause)
            response: str | StructuredGenerationFailure = self.responses.popleft()
            if isinstance(response, StructuredGenerationFailure):
                raise response
            return StructuredResponse(text=response, finish_reason="stop")
        finally:
            self.closed = True


def structured_request() -> StructuredRequest:
    return StructuredRequest(
        messages=(StructuredMessage(role=MessageRole.USER, content="Read the source."),),
        profile=ModelProfile("test", StructuredMode.JSON_TEXT, 4096, 512),
    )


def policy() -> GenerationPolicy:
    return GenerationPolicy(1, 60, 6, 8, 0, 3500, backoff_max=0, jitter=0)


def budget(*, requests: int = 4, network: int = 1, corrections: int = 1) -> ExecutionBudget:
    return ExecutionBudget(
        max_total_requests=requests,
        deadline=monotonic() + 10,
        request_timeout=5,
        network_retries=network,
        correction_retries=corrections,
    )


@pytest.mark.anyio
async def test_strict_schema_repair_keeps_model_and_mode_and_reports_no_source_content() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":"sensitive source value"}', '{"count":2}'])
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, policy(), ContentLengthCounter()
    )
    execution: ExecutionBudget = budget()
    result: Answer = await generator.generate(structured_request(), Answer, execution)
    assert result.count == 2
    assert execution.requests == 2
    assert execution.corrections == 1
    assert model.requests[1].profile == model.requests[0].profile
    feedback: str = model.requests[1].messages[-1].content
    assert "sensitive source value" not in feedback
    assert "schema" in feedback


@pytest.mark.anyio
async def test_mixed_network_and_json_retries_share_one_budget_across_generate_calls() -> None:
    model: ScriptedModel = ScriptedModel(
        [
            StructuredGenerationFailure(StructuredErrorCode.CONNECTION, retryable=True),
            "invalid",
            '{"count":2}',
        ]
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, policy(), ContentLengthCounter()
    )
    execution: ExecutionBudget = budget(requests=3)
    result: Answer = await generator.generate(structured_request(), Answer, execution)
    assert result.count == 2
    assert execution.requests == 3
    with pytest.raises(StructuredGenerationFailure) as error:
        await generator.generate(structured_request(), Answer, execution)
    assert error.value.reason == StructuredErrorCode.BUDGET_EXHAUSTED
    assert len(model.requests) == 3


@pytest.mark.anyio
async def test_zero_correction_retries_never_accepts_invalid_json_or_coerces_types() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":"2"}'])
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, policy(), ContentLengthCounter()
    )
    with pytest.raises(StructuredGenerationFailure) as error:
        await generator.generate(structured_request(), Answer, budget(corrections=0))
    assert error.value.reason == StructuredErrorCode.SCHEMA_INVALID
    assert len(model.requests) == 1


@pytest.mark.anyio
async def test_cancelled_budget_never_starts_a_request() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":2}'])
    execution: ExecutionBudget = budget()
    execution.cancellation = asyncio.Event()
    execution.cancellation.set()
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.CANCELLED
    assert not model.requests


@pytest.mark.parametrize("text", ['{"count":1,"count":2}', '{"count":NaN}', '{"count":Infinity}'])
def test_json_must_not_contain_duplicate_keys_or_non_json_numbers(text: str) -> None:
    with pytest.raises(StructuredGenerationFailure) as error:
        validate_response(StructuredResponse(text=text, finish_reason="stop"), Answer)
    assert error.value.reason == StructuredErrorCode.JSON_INVALID


@pytest.mark.anyio
async def test_cancellation_event_closes_in_flight_request_without_retry() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":2}'], pause=5)
    execution: ExecutionBudget = budget()
    execution.cancellation = asyncio.Event()
    task: asyncio.Task[Answer] = asyncio.create_task(
        StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    )
    await model.started.wait()
    execution.cancellation.set()
    with pytest.raises(StructuredGenerationFailure) as error:
        await asyncio.wait_for(task, timeout=1)
    assert error.value.reason == StructuredErrorCode.CANCELLED
    assert execution.requests == 1
    assert model.closed


@pytest.mark.anyio
async def test_overall_deadline_includes_rate_limit_backoff() -> None:
    model: ScriptedModel = ScriptedModel(
        [
            StructuredGenerationFailure(
                StructuredErrorCode.RATE_LIMITED, retryable=True, retry_after=10
            )
        ]
    )
    execution: ExecutionBudget = budget()
    execution.deadline = monotonic() + 0.02
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.DEADLINE_EXCEEDED
    assert execution.requests == 1


@pytest.mark.anyio
async def test_per_request_timeout_is_typed_and_closes_upstream() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":2}'], pause=5)
    execution: ExecutionBudget = budget(requests=1, network=0)
    execution.request_timeout = 0.01
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.TIMEOUT
    assert model.closed


@pytest.mark.anyio
async def test_budget_is_persisted_before_adapter_and_restorable_without_reset() -> None:
    observed: list[BudgetUsage] = []
    model: ScriptedModel = ScriptedModel(['{"count":2}'])

    async def persist(usage: BudgetUsage) -> None:
        assert not model.requests
        observed.append(usage)

    execution: ExecutionBudget = budget(requests=3)
    execution.requests = 2
    execution.on_usage = persist
    await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
        structured_request(), Answer, execution
    )
    assert observed == [BudgetUsage(3, 0, 0)]
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.BUDGET_EXHAUSTED


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (StructuredResponse[Answer]("", "stop"), StructuredErrorCode.EMPTY_RESPONSE),
        (StructuredResponse[Answer](" ", "stop"), StructuredErrorCode.EMPTY_RESPONSE),
        (StructuredResponse[Answer]('{"count":', "length"), StructuredErrorCode.TRUNCATED_RESPONSE),
        (StructuredResponse[Answer]('{"count":2}', None), StructuredErrorCode.INVALID_RESPONSE),
        (
            StructuredResponse[Answer]('{"count":2}', "tool_calls"),
            StructuredErrorCode.INVALID_RESPONSE,
        ),
        (StructuredResponse[Answer]("refusal", "stop", refused=True), StructuredErrorCode.REFUSAL),
    ],
)
def test_partial_empty_or_refused_responses_never_become_results(
    response: StructuredResponse[Answer], reason: StructuredErrorCode
) -> None:
    with pytest.raises(StructuredGenerationFailure) as error:
        validate_response(response, Answer)
    assert error.value.reason == reason


@pytest.mark.anyio
async def test_direct_task_cancellation_propagates_and_closes_upstream() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":2}'], pause=5)
    task: asyncio.Task[Answer] = asyncio.create_task(
        StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, budget()
        )
    )
    await model.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert model.closed


@pytest.mark.anyio
async def test_exhausted_class_retry_counter_is_restored() -> None:
    model: ScriptedModel = ScriptedModel(
        [StructuredGenerationFailure(StructuredErrorCode.CONNECTION, retryable=True)]
    )
    execution: ExecutionBudget = budget()
    execution.requests = 1
    execution.network_failures = 1
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.CONNECTION
    assert execution.requests == 2
    assert len(model.requests) == 1


@pytest.mark.anyio
async def test_error_class_change_cannot_reset_global_request_cap() -> None:
    model: ScriptedModel = ScriptedModel(
        [StructuredGenerationFailure(StructuredErrorCode.CONNECTION, retryable=True), "invalid"]
    )
    execution: ExecutionBudget = budget(requests=2)
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.BUDGET_EXHAUSTED
    assert len(model.requests) == 2


@pytest.mark.anyio
async def test_expired_deadline_never_starts_generation() -> None:
    model: ScriptedModel = ScriptedModel(['{"count":2}'])
    execution: ExecutionBudget = budget()
    execution.deadline = monotonic() - 1
    with pytest.raises(StructuredGenerationFailure) as error:
        await StructuredOutputGenerator(model, policy(), ContentLengthCounter()).generate(
            structured_request(), Answer, execution
        )
    assert error.value.reason == StructuredErrorCode.DEADLINE_EXCEEDED
    assert not model.requests

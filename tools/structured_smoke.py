"""Measure local structured-output capabilities without loading or changing model weights."""

import argparse
import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from time import monotonic
from typing import Final, Literal
from urllib.parse import SplitResult, urlsplit

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredModel,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.prompts.extraction_prompt import SYSTEM_PROMPT
from solution_architect_ai.application.protocols.chat_protocols import TokenCounter
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.structured_response_validator import (
    validate_response,
)
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.structured import LangChainStructuredModel
from tools.structured_smoke_models import AttemptReport, CaseReport, SmokeModel, SmokeReport

_RESPONSE_FAILURES: Final[frozenset[StructuredErrorCode]] = frozenset(
    {
        StructuredErrorCode.JSON_INVALID,
        StructuredErrorCode.SCHEMA_INVALID,
        StructuredErrorCode.EMPTY_RESPONSE,
        StructuredErrorCode.TRUNCATED_RESPONSE,
        StructuredErrorCode.REFUSAL,
        StructuredErrorCode.INVALID_RESPONSE,
    }
)


class SmokeAnswer(SmokeModel):
    count: int


@dataclass(frozen=True)
class CaseDefinition:
    name: str
    mode: StructuredMode
    schema: type[BaseModel]
    messages: tuple[StructuredMessage, ...]
    expected: Literal["validated", "timeout", "cancelled"] = "validated"


class SmokeTrace:
    def __init__(self) -> None:
        self.http_requests: int = 0
        self.entered: asyncio.Event = asyncio.Event()
        self.attempts: list[AttemptReport] = []

    async def request(self, _request: httpx.Request) -> None:
        self.http_requests += 1


class ObservedModel:
    def __init__(self, adapter: StructuredModel, trace: SmokeTrace) -> None:
        self.adapter: StructuredModel = adapter
        self.trace: SmokeTrace = trace

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResponse[T]:
        self.trace.entered.set()
        started: float = monotonic()
        report: AttemptReport = AttemptReport()
        try:
            response: StructuredResponse[T] = await self.adapter.invoke(request, schema)
            report = inspect_response(response, schema)
            return response
        except StructuredGenerationFailure as error:
            report.error_code = error.reason.value
            if error.reason in _RESPONSE_FAILURES:
                report.response_valid = False
            raise
        except asyncio.CancelledError:
            report.error_code = "cancelled"
            raise
        finally:
            report.elapsed_seconds = monotonic() - started
            self.trace.attempts.append(report)


def inspect_response[T: BaseModel](
    response: StructuredResponse[T], schema: type[T]
) -> AttemptReport:
    report: AttemptReport = AttemptReport(
        input_tokens=response.input_tokens or None, output_tokens=response.output_tokens or None
    )
    try:
        validate_response(response, schema)
    except StructuredGenerationFailure as error:
        report.response_valid, report.error_code = False, error.reason.value
    else:
        report.response_valid = True
    return report


def validate_url(value: str) -> str:
    url: SplitResult = urlsplit(value)
    local: bool = url.hostname == "localhost"
    try:
        local = local or ip_address(url.hostname or "").is_loopback
        valid_port: bool = url.port is None or 1 <= url.port <= 65535
    except ValueError:
        valid_port = False
    if not local or not valid_port or url.scheme not in {"http", "https"}:
        raise ValueError(
            "Use an explicit loopback HTTP(S) /v1 endpoint without credentials or query"
        )
    if any((url.username, url.password, url.query, url.fragment)) or url.path.rstrip("/") != "/v1":
        raise ValueError(
            "Use an explicit loopback HTTP(S) /v1 endpoint without credentials or query"
        )
    return value.rstrip("/")


async def stop_after_entry(
    task: asyncio.Task[BaseModel], trace: SmokeTrace, cancellation: asyncio.Event
) -> BaseModel:
    entered: asyncio.Task[bool] = asyncio.create_task(trace.entered.wait())
    try:
        await asyncio.wait((task, entered), return_when=asyncio.FIRST_COMPLETED)
        if trace.entered.is_set():
            cancellation.set()
        return await task
    finally:
        entered.cancel()
        task.cancel()
        await asyncio.gather(task, entered, return_exceptions=True)


def result_summary(value: BaseModel) -> dict[str, int]:
    if isinstance(value, SmokeAnswer):
        return {"count": value.count}
    payload: dict[str, object] = value.model_dump()
    return {
        name: len(items)
        for name, items in payload.items()
        if name in {"requirements", "gaps", "contradictions"} and isinstance(items, list)
    }


def usage(attempts: list[AttemptReport], *, output: bool) -> int | None:
    values: list[int] = [
        value
        for attempt in attempts
        if (value := attempt.output_tokens if output else attempt.input_tokens) is not None
    ]
    return sum(values) if values else None


async def measure_case(
    case: CaseDefinition,
    profile: ModelProfile,
    trace: SmokeTrace,
    adapter: StructuredModel,
    tokens: TokenCounter,
) -> CaseReport:
    negative: bool = case.expected != "validated"
    cancellation: asyncio.Event = asyncio.Event()
    budget: ExecutionBudget = ExecutionBudget(
        1 if negative else 4,
        monotonic() + 60,
        0.001 if case.expected == "timeout" else 30,
        network_retries=0 if negative else 1,
        correction_retries=0 if negative else 2,
        cancellation=cancellation,
    )
    policy: GenerationPolicy = GenerationPolicy(
        1, 60, 3, 4, 0.1, profile.context_window - profile.output_limit, backoff_max=0.2, jitter=0
    )
    started: float = monotonic()
    observed: str = "validated"
    summary: dict[str, int] = {}
    try:
        task: asyncio.Task[BaseModel] = asyncio.create_task(
            StructuredOutputGenerator(ObservedModel(adapter, trace), policy, tokens).generate(
                StructuredRequest(case.messages, replace(profile, mode=case.mode)),
                case.schema,
                budget,
            )
        )
        result: BaseModel = (
            await stop_after_entry(task, trace, cancellation)
            if case.expected == "cancelled"
            else await task
        )
        summary = result_summary(result)
    except StructuredGenerationFailure as error:
        observed = error.reason.value
    return CaseReport(
        name=case.name,
        mode=case.mode.value,
        schema_name=case.schema.__name__,
        schema_sha256=sha256(
            json.dumps(case.schema.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
        expected=case.expected,
        observed=observed,
        expected_outcome_observed=observed == case.expected,
        requests=budget.requests,
        http_requests=trace.http_requests,
        corrections=budget.corrections,
        network_failures=budget.network_failures,
        received_responses=sum(item.response_valid is not None for item in trace.attempts),
        valid_responses=sum(item.response_valid is True for item in trace.attempts),
        input_tokens=usage(trace.attempts, output=False),
        output_tokens=usage(trace.attempts, output=True),
        elapsed_seconds=monotonic() - started,
        adapter_entered=trace.entered.is_set(),
        summary=summary,
        attempts=trace.attempts,
    )


def cases() -> list[CaseDefinition]:
    answer: tuple[StructuredMessage, ...] = (
        StructuredMessage(MessageRole.SYSTEM, "Return JSON matching the schema."),
        StructuredMessage(MessageRole.USER, "Return count=2."),
    )
    requirements: tuple[StructuredMessage, ...] = (
        StructuredMessage(MessageRole.SYSTEM, SYSTEM_PROMPT),
        StructuredMessage(
            MessageRole.USER,
            json.dumps(
                {
                    "analysis_scope": "",
                    "fragments": [
                        {
                            "fragment_id": "00000000-0000-4000-8000-000000000001",
                            "text": "Система должна сохранять отчёт в формате CSV.",
                            "section": "Функции",
                            "path": "",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ),
    )
    selected: list[CaseDefinition] = []
    mode: StructuredMode
    for mode in StructuredMode:
        selected.append(CaseDefinition(f"answer_{mode.value}", mode, SmokeAnswer, answer))
        selected.append(
            CaseDefinition(f"requirements_{mode.value}", mode, RequirementsExtraction, requirements)
        )
    selected.append(
        CaseDefinition("timeout_1ms", StructuredMode.JSON_TEXT, SmokeAnswer, answer, "timeout")
    )
    selected.append(
        CaseDefinition(
            "cancellation_after_entry", StructuredMode.JSON_TEXT, SmokeAnswer, answer, "cancelled"
        )
    )
    return selected


async def run(
    base_url: str, model_name: str, context_window: int, output_limit: int
) -> SmokeReport:
    selected: list[CaseReport] = []
    tokens: TokenCounter = LangChainTokenCounter(2, chat_prompt=False)
    profile: ModelProfile = ModelProfile(
        model_name, StructuredMode.JSON_TEXT, context_window, output_limit, 256
    )
    for case in cases():
        trace: SmokeTrace = SmokeTrace()
        sync_client: httpx.Client
        client: httpx.AsyncClient
        with httpx.Client(trust_env=False, follow_redirects=False) as sync_client:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, event_hooks={"request": [trace.request]}
            ) as client:
                model: ChatOpenAI = ChatOpenAI(
                    model=model_name,
                    base_url=base_url,
                    api_key="local-capability-smoke",
                    temperature=0,
                    max_completion_tokens=output_limit,
                    max_retries=0,
                    timeout=30,
                    http_client=sync_client,
                    http_async_client=client,
                    http_socket_options=(),
                    streaming=False,
                    stream_usage=False,
                )
                report: CaseReport = await measure_case(
                    case, profile, trace, LangChainStructuredModel(model), tokens
                )
        selected.append(report)
        print(
            f"{report.name}: {report.observed}; HTTP={report.http_requests}; requests={report.requests}",
            flush=True,
        )
    return SmokeReport(
        measured_at=datetime.now(UTC),
        base_url=base_url,
        model=model_name,
        context_window=context_window,
        output_limit=output_limit,
        service_tokens=256,
        approximate_chars_per_token=2,
        cases=selected,
        notes=[
            "No model weights or server settings are changed. No SDK retries or hidden format fallback.",
            "Schema validity is independent of source/semantic truth. The synthetic fragment has no SQL source record.",
            "Context rejection happens before HTTP, including conservative native-schema accounting. Unknown usage is null.",
            "HTTP hooks count outgoing requests; reservations and adapter entry may precede an actual network request.",
            "Cancellation proves local task cleanup after adapter entry, not termination of server-side GPU computation.",
        ],
    )


def configuration(args: argparse.Namespace) -> tuple[str, str, int, int, Path]:
    base_url: str = validate_url(str(args.base_url))
    model_name: str = str(args.model)
    context_window: int = args.context_window
    output_limit: int = args.output_limit
    output: Path = args.output
    if not model_name.strip() or not 0 < output_limit < context_window:
        raise ValueError("Model name and context/output limits are required")
    return base_url, model_name, context_window, output_limit, output


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--context-window", required=True, type=int)
    parser.add_argument("--output-limit", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args: argparse.Namespace = parser.parse_args()
    try:
        base_url: str
        model_name: str
        context_window: int
        output_limit: int
        output: Path
        base_url, model_name, context_window, output_limit, output = configuration(args)
        report: SmokeReport = asyncio.run(
            run(base_url, model_name, context_window, output_limit),
            loop_factory=asyncio.SelectorEventLoop,
        )
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        parser.exit(2, "Invalid local smoke configuration or output path.\n")


if __name__ == "__main__":
    main()

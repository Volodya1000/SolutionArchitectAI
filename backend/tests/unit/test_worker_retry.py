import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event
from typing import Final
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    ChatView,
    MessageView,
    ModelStatus,
    PendingRun,
    RunView,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore, Chunk
from solution_architect_ai.application.protocols.transaction_protocols import (
    TransactionRetriesExhausted,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus, resolve_transition
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

type Response = tuple[Chunk | GenerationFailure, ...]
POLICY: Final[GenerationPolicy] = GenerationPolicy(1, 10, 2, 3, 0, 4096, jitter=0)
pytestmark: pytest.MarkDecorator = pytest.mark.anyio


class ScriptedLLM:
    def __init__(self, responses: list[Response]) -> None:
        self.responses: list[Response] = responses
        self.attempts: int = 0

    async def status(self) -> ModelStatus:
        return ModelStatus(model="fake", available=True)

    @asynccontextmanager
    async def stream(self, messages: list[MessageView]) -> AsyncIterator[AsyncIterator[Chunk]]:
        assert messages[-1].content == "question"
        response: Response = self.responses[self.attempts]
        self.attempts += 1
        chunks: AsyncGenerator[Chunk] = self.chunks(response)
        async with aclosing(chunks):
            yield chunks

    async def chunks(self, response: Response) -> AsyncGenerator[Chunk]:
        item: Chunk | GenerationFailure
        for item in response:
            if isinstance(item, GenerationFailure):
                raise item
            yield item


class MemoryRun:
    def __init__(self) -> None:
        self.record: RunView = RunView(
            id=uuid4(),
            chat_id=uuid4(),
            assistant_message_id=uuid4(),
            status=RunStatus.QUEUED,
            sequence=0,
            content="",
            incomplete=True,
            error_code=None,
            model="fake",
            config_digest="x",
            created_at=datetime.now(UTC),
        )
        self.checked_output: asyncio.Event = asyncio.Event()
        self.store: MagicMock = MagicMock(spec_set=ChatStore)
        self.store.queries.get_run = AsyncMock(side_effect=self.get_run)
        self.store.queries.snapshot = AsyncMock(
            return_value=ChatSnapshot(
                chat=ChatView(
                    id=self.record.chat_id,
                    task_id=uuid4(),
                    title="test",
                    created_at=self.record.created_at,
                ),
                messages=[
                    MessageView(
                        id=uuid4(),
                        role=MessageRole.USER,
                        content="question",
                        position=1,
                        incomplete=False,
                    )
                ],
                runs=[self.record],
            )
        )
        self.store.append = AsyncMock(side_effect=self.append)
        self.store.set_status = AsyncMock(side_effect=self.set_status)

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ChatStore]:
        yield self.store

    async def get_run(self, run_id: UUID) -> RunView:
        assert run_id == self.record.id
        if self.record.status == RunStatus.RUNNING:
            self.checked_output.set()
        return self.record

    async def append(self, run_id: UUID, text: str) -> bool:
        assert run_id == self.record.id
        self.record.content += text
        return True

    async def set_status(
        self, run_id: UUID, target: RunStatus, error: RunErrorCode | None = None
    ) -> RunView:
        assert run_id == self.record.id
        self.record.status = resolve_transition(self.record.status, target, error)
        self.record.error_code = error
        return self.record

    def pending(self) -> PendingRun:
        return PendingRun(
            id=self.record.id, status=self.record.status, created_at=self.record.created_at
        )


def failure(*, retryable: bool = True, retry_after: float = 0) -> GenerationFailure:
    return GenerationFailure(
        RunErrorCode.LLM_UNAVAILABLE, retryable=retryable, retry_after=retry_after
    )


@pytest.mark.parametrize(("retries", "requests", "expected"), [(0, 4, 1), (3, 2, 2), (1, 4, 2)])
async def test_worker_stops_at_the_smaller_request_budget(
    retries: int, requests: int, expected: int
) -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([(failure(),)] * expected)
    worker: RunWorker = RunWorker(
        stores, llm, replace(POLICY, retries=retries, requests=requests), LangChainTokenCounter(1)
    )
    await worker.execute(stores.pending())
    assert llm.attempts == expected
    assert stores.record.status == RunStatus.FAILED
    assert stores.record.error_code == RunErrorCode.LLM_UNAVAILABLE


async def test_transient_empty_attempt_can_be_retried_to_completion() -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([(failure(),), (Chunk("answer", "stop"),)])
    worker: RunWorker = RunWorker(stores, llm, POLICY, LangChainTokenCounter(1))
    await worker.execute(stores.pending())
    assert llm.attempts == 2
    assert stores.record.status == RunStatus.COMPLETED
    assert stores.record.content == "answer"


async def test_exhausted_recovery_for_one_run_does_not_starve_queued_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stores: MemoryRun = MemoryRun()
    worker: RunWorker = RunWorker(
        stores, ScriptedLLM([(Chunk("answer", "stop"),)]), POLICY, LangChainTokenCounter(1)
    )
    poison: PendingRun = PendingRun(
        id=uuid4(), status=RunStatus.RUNNING, created_at=stores.record.created_at
    )
    stores.store.queries.pending = AsyncMock(return_value=[poison, stores.pending()])

    async def blocked_recovery(
        run_id: UUID, _status: RunStatus, _error: RunErrorCode | None = None
    ) -> None:
        assert run_id == poison.id
        raise TransactionRetriesExhausted("transaction_conflict")

    monkeypatch.setattr(worker, "finish", blocked_recovery)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        await worker.dispatch(group)
        monkeypatch.undo()
    assert stores.record.status == RunStatus.COMPLETED
    assert stores.record.content == "answer"


@pytest.mark.parametrize(
    ("response", "content"),
    [
        ((failure(retryable=False),), ""),
        ((Chunk("first"), failure()), "first"),
    ],
)
async def test_nonretryable_or_persisted_output_ends_attempts(
    response: Response, content: str
) -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([response])
    worker: RunWorker = RunWorker(stores, llm, POLICY, LangChainTokenCounter(1))
    await worker.execute(stores.pending())
    assert llm.attempts == 1
    assert stores.record.status == RunStatus.FAILED
    assert stores.record.error_code == RunErrorCode.LLM_UNAVAILABLE
    assert stores.record.content == content


async def test_cancellation_interrupts_retry_after_without_another_request() -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([(failure(retry_after=60),)])
    worker: RunWorker = RunWorker(stores, llm, POLICY, LangChainTokenCounter(1))
    group: asyncio.TaskGroup
    async with asyncio.timeout(3), asyncio.TaskGroup() as group:
        task: asyncio.Task[None] = group.create_task(worker.execute(stores.pending()))
        await stores.checked_output.wait()
        await stores.set_status(stores.record.id, RunStatus.CANCELLING)
        task.cancel()
    assert task.cancelled()
    assert llm.attempts == 1
    assert stores.record.status == RunStatus.CANCELLED


async def test_total_deadline_interrupts_server_retry_after() -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([(failure(retry_after=60),)])
    worker: RunWorker = RunWorker(
        stores, llm, replace(POLICY, deadline=1), LangChainTokenCounter(1)
    )
    async with asyncio.timeout(3):
        await worker.execute(stores.pending())
    assert llm.attempts == 1
    assert stores.record.status == RunStatus.FAILED
    assert stores.record.error_code == RunErrorCode.DEADLINE_EXCEEDED


class BlockingCounter:
    def __init__(self) -> None:
        self.release: Event = Event()

    def count(self, messages: list[MessageView]) -> int:
        self.release.wait(timeout=2)
        return len(messages)


async def test_total_deadline_remains_responsive_during_context_estimation() -> None:
    stores: MemoryRun = MemoryRun()
    llm: ScriptedLLM = ScriptedLLM([(Chunk("answer", "stop"),)])
    tokens: BlockingCounter = BlockingCounter()
    worker: RunWorker = RunWorker(stores, llm, replace(POLICY, deadline=0.1), tokens)
    try:
        async with asyncio.timeout(1):
            await worker.execute(stores.pending())
        assert llm.attempts == 0
        assert stores.record.status == RunStatus.FAILED
        assert stores.record.error_code == RunErrorCode.DEADLINE_EXCEEDED
    finally:
        tokens.release.set()

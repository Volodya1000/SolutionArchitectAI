import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from random import SystemRandom
from uuid import UUID

from solution_architect_ai.application.contracts import MessageView, RunView, StorageUnavailable
from solution_architect_ai.application.ports import LLM, GenerationFailure, StoreFactory
from solution_architect_ai.domain.runs import RunStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationPolicy:
    concurrency: int
    deadline: float
    retries: int
    requests: int
    backoff: float
    input_budget: int
    backoff_max: float = 2
    jitter: float = 0.1


def retry_delay(policy: GenerationPolicy, attempt: int, retry_after: float) -> float:
    exponential = min(policy.backoff * (2.0**attempt), policy.backoff_max)
    return max(exponential, retry_after) + SystemRandom().uniform(0, policy.jitter)


class RunWorker:
    def __init__(self, stores: StoreFactory, llm: LLM, policy: GenerationPolicy) -> None:
        self.stores = stores
        self.llm = llm
        self.policy = policy
        self.active: dict[UUID, asyncio.Task[None]] = {}
        self.stopping = asyncio.Event()

    async def recover(self) -> None:
        async with self.stores.open() as store:
            for run in await store.pending():
                await store.set_status(run.id, RunStatus.FAILED, "process_interrupted")

    async def serve(self) -> None:
        async with asyncio.TaskGroup() as group:
            while not self.stopping.is_set():
                try:
                    await self.dispatch(group)
                except StorageUnavailable:
                    logger.warning("worker_database_unavailable")
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=0.1)
                except TimeoutError:
                    continue
            for task in self.active.values():
                task.cancel()

    async def dispatch(self, group: asyncio.TaskGroup) -> None:
        async with self.stores.open() as store:
            pending = await store.pending()
        for run in pending:
            await self.dispatch_run(group, run)

    async def dispatch_run(self, group: asyncio.TaskGroup, run: RunView) -> None:
        active = self.active.get(run.id)
        if active is not None:
            if run.status == RunStatus.CANCELLING:
                active.cancel()
            return
        if run.status == RunStatus.CANCELLING:
            await self.finish(run.id, RunStatus.CANCELLED)
        elif run.status == RunStatus.RUNNING:
            await self.finish(run.id, RunStatus.FAILED, "processing_interrupted")
        elif len(self.active) < self.policy.concurrency:
            self.active[run.id] = group.create_task(self.execute(run.id))

    async def finish(self, run_id: UUID, status: RunStatus, error: str | None = None) -> None:
        async with self.stores.open() as store:
            run = await store.set_status(run_id, status, error)
        logger.info(
            "run_status run_id=%s model=%s status=%s sequence=%s config_digest=%s output_characters=%s",
            run.id,
            run.model,
            run.status,
            run.sequence,
            run.config_digest,
            len(run.content),
        )

    async def execute(self, run_id: UUID) -> None:
        try:
            async with self.stores.open() as store:
                run = await store.get_run(run_id)
            elapsed = (datetime.now(UTC) - run.created_at).total_seconds()
            async with asyncio.timeout(max(0, self.policy.deadline - elapsed)):
                await self.generate(run_id)
        except asyncio.CancelledError:
            target = RunStatus.FAILED if self.stopping.is_set() else RunStatus.CANCELLED
            await self.safe_finish(
                run_id, target, "process_interrupted" if self.stopping.is_set() else None
            )
            raise
        except GenerationFailure as error:
            await self.safe_finish(run_id, RunStatus.FAILED, error.code)
        except TimeoutError:
            await self.safe_finish(run_id, RunStatus.FAILED, "deadline_exceeded")
        except StorageUnavailable:
            logger.warning("run_database_unavailable run_id=%s", run_id)
        finally:
            self.active.pop(run_id, None)

    async def safe_finish(self, run_id: UUID, status: RunStatus, error: str | None) -> None:
        try:
            await self.finish(run_id, status, error)
        except StorageUnavailable:
            logger.warning("run_status_pending run_id=%s", run_id)

    async def generate(self, run_id: UUID) -> None:
        async with self.stores.open() as store:
            run = await store.get_run(run_id)
            if run.status != RunStatus.QUEUED:
                return
            await store.set_status(run_id, RunStatus.RUNNING)
            snapshot = await store.snapshot(run.chat_id)
        messages = self.context(snapshot.messages)
        attempts = min(self.policy.retries + 1, self.policy.requests)
        for attempt in range(attempts):
            delay = await self.attempt(run_id, messages, attempt, attempt + 1 == attempts)
            if delay is None:
                await self.finish(run_id, RunStatus.COMPLETED)
                return
            await asyncio.sleep(delay)

    async def attempt(
        self, run_id: UUID, messages: list[MessageView], attempt: int, last: bool
    ) -> float | None:
        try:
            await self.consume(run_id, messages)
        except GenerationFailure as error:
            async with self.stores.open() as store:
                current = await store.get_run(run_id)
            if current.content or not error.retryable or last:
                raise
            return retry_delay(self.policy, attempt, error.retry_after)
        return None

    def context(self, messages: list[MessageView]) -> list[MessageView]:
        selected = [item for item in messages if item.role == "user" or not item.incomplete]
        if not selected or len(selected[-1].content.encode()) > self.policy.input_budget:
            raise GenerationFailure("context_too_large")
        while sum(len(item.content.encode()) for item in selected) > self.policy.input_budget:
            selected.pop(0)
        return selected

    async def consume(self, run_id: UUID, messages: list[MessageView]) -> None:
        finish: str | None = None
        has_text = False
        async with self.llm.stream(messages) as chunks:
            async for chunk in chunks:
                has_text = has_text or bool(chunk.text.strip())
                finish = chunk.finish or finish
                if chunk.text:
                    await self.flush(run_id, chunk.text)
        if not has_text:
            raise GenerationFailure("empty_response")
        if finish != "stop":
            raise GenerationFailure("incomplete_response")

    async def flush(self, run_id: UUID, text: str) -> None:
        async with self.stores.open() as store:
            if not await store.append(run_id, text):
                raise asyncio.CancelledError

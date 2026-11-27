import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from tenacity import AsyncRetrying

from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.context.chat_context_builder import select_context
from solution_architect_ai.application.errors.chat_errors import (
    GenerationFailure,
    StorageUnavailable,
)
from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    MessageView,
    PendingRun,
    RunView,
)
from solution_architect_ai.application.protocols.chat_protocols import (
    LLM,
    ChatStore,
    Chunk,
    TokenCounter,
)
from solution_architect_ai.application.protocols.discussion_protocols import DiscussionContext
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus

logger: logging.Logger = logging.getLogger(__name__)


class RunWorker:
    def __init__(
        self,
        chat_store_context: StoreContext[ChatStore],
        llm: LLM,
        generation_policy: GenerationPolicy,
        chat_token_counter: TokenCounter,
        capacity: GenerationCapacity | None = None,
        discussion_context: DiscussionContext | None = None,
    ) -> None:
        self.chat_store_context: StoreContext[ChatStore] = chat_store_context
        self.llm: LLM = llm
        self.generation_policy: GenerationPolicy = generation_policy
        self.chat_token_counter: TokenCounter = chat_token_counter
        self.capacity: GenerationCapacity = capacity or GenerationCapacity(
            generation_policy.concurrency
        )
        self.active: dict[UUID, asyncio.Task[None]] = {}
        self.stopping: asyncio.Event = asyncio.Event()
        self.discussion_context: DiscussionContext | None = discussion_context

    async def recover(self) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            run: PendingRun
            for run in await store.queries.pending():
                await store.set_status(run.id, RunStatus.FAILED, RunErrorCode.PROCESS_INTERRUPTED)

    async def serve(self) -> None:
        group: asyncio.TaskGroup
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
            task: asyncio.Task[None]
            for task in self.active.values():
                task.cancel()

    async def dispatch(self, group: asyncio.TaskGroup) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            pending: list[PendingRun] = await store.queries.pending()
        run: PendingRun
        for run in pending:
            await self.dispatch_run(group, run)

    async def dispatch_run(self, group: asyncio.TaskGroup, run: PendingRun) -> None:
        active: asyncio.Task[None] | None = self.active.get(run.id)
        if active is not None:
            if run.status == RunStatus.CANCELLING:
                active.cancel()
            return
        if run.status == RunStatus.CANCELLING:
            await self.finish(run.id, RunStatus.CANCELLED)
        elif run.status == RunStatus.RUNNING:
            await self.finish(run.id, RunStatus.FAILED, RunErrorCode.PROCESSING_INTERRUPTED)
        elif len(self.active) < self.generation_policy.concurrency:
            self.active[run.id] = group.create_task(self.execute(run))

    async def finish(
        self, run_id: UUID, status: RunStatus, error: RunErrorCode | None = None
    ) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            run: RunView = await store.set_status(run_id, status, error)
        logger.info(
            "run_status run_id=%s chat_id=%s model=%s status=%s sequence=%s error_code=%s config_digest=%s output_characters=%s",
            run.id,
            run.chat_id,
            run.model,
            run.status,
            run.sequence,
            run.error_code,
            run.config_digest,
            len(run.content),
        )

    async def execute(self, run: PendingRun) -> None:
        run_id: UUID = run.id
        try:
            elapsed: float = (datetime.now(UTC) - run.created_at).total_seconds()
            async with asyncio.timeout(max(0, self.generation_policy.deadline - elapsed)):
                async with self.capacity.slots:
                    await self.generate(run_id)
        except asyncio.CancelledError:
            if self.stopping.is_set():
                await self.safe_finish(run_id, RunStatus.FAILED, RunErrorCode.PROCESS_INTERRUPTED)
            else:
                await self.safe_finish(run_id, RunStatus.CANCELLED, None)
            raise
        except GenerationFailure as error:
            await self.safe_finish(run_id, RunStatus.FAILED, error.code)
        except TimeoutError:
            await self.safe_finish(run_id, RunStatus.FAILED, RunErrorCode.DEADLINE_EXCEEDED)
        except StorageUnavailable:
            logger.warning("run_database_unavailable run_id=%s", run_id)
        finally:
            self.active.pop(run_id, None)

    async def safe_finish(
        self, run_id: UUID, status: RunStatus, error: RunErrorCode | None
    ) -> None:
        try:
            await self.finish(run_id, status, error)
        except StorageUnavailable:
            logger.warning("run_status_pending run_id=%s", run_id)

    async def generate(self, run_id: UUID) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            run: RunView = await store.queries.get_run(run_id)
            if run.status != RunStatus.QUEUED:
                return
            claimed: RunView = await store.set_status(run_id, RunStatus.RUNNING)
            if claimed.status != RunStatus.RUNNING:
                return
            snapshot: ChatSnapshot = await store.queries.snapshot(run.chat_id)
        prefix: list[MessageView] = (
            []
            if self.discussion_context is None
            else await self.discussion_context.messages(run.chat_id)
        )
        messages: list[MessageView] = await asyncio.to_thread(
            select_context,
            snapshot.messages,
            self.generation_policy.input_budget,
            self.chat_token_counter,
            prefix,
        )
        retries: AsyncRetrying = self.generation_policy.retrying(partial(self.can_retry, run_id))
        await retries(self.consume, run_id, messages)
        await self.finish(run_id, RunStatus.COMPLETED)

    async def can_retry(self, run_id: UUID, error: BaseException) -> bool:
        if not isinstance(error, GenerationFailure) or not error.retryable:
            return False
        store: ChatStore
        async with self.chat_store_context.open() as store:
            current: RunView = await store.queries.get_run(run_id)
        return not current.content

    async def consume(self, run_id: UUID, messages: list[MessageView]) -> None:
        finish: str | None = None
        has_text: bool = False
        chunks: AsyncIterator[Chunk]
        async with self.llm.stream(messages) as chunks:
            chunk: Chunk
            async for chunk in chunks:
                has_text = has_text or bool(chunk.text.strip())
                finish = chunk.finish or finish
                if chunk.text:
                    await self.flush(run_id, chunk.text)
        if not has_text:
            raise GenerationFailure(RunErrorCode.EMPTY_RESPONSE)
        if finish != "stop":
            raise GenerationFailure(RunErrorCode.INCOMPLETE_RESPONSE)

    async def flush(self, run_id: UUID, text: str) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            if not await store.append(run_id, text):
                raise asyncio.CancelledError

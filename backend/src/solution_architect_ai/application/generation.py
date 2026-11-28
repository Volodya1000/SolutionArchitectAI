import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

from tenacity import AsyncRetrying

from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.context.chat_context_builder import select_context
from solution_architect_ai.application.context.discussion_citations import DiscussionCitationStream
from solution_architect_ai.application.errors.chat_errors import (
    GenerationFailure,
    StorageUnavailable,
    StoredDataCorrupt,
)
from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    MessageView,
    PendingRun,
    RunView,
)
from solution_architect_ai.application.models.discussion_input_models import PreparedDiscussion
from solution_architect_ai.application.protocols.chat_protocols import (
    LLM,
    ChatStore,
    Chunk,
    TokenCounter,
)
from solution_architect_ai.application.protocols.discussion_protocols import DiscussionContext
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.protocols.transaction_protocols import (
    DirectTransactionRunner,
    TransactionRetriesExhausted,
    TransactionRunner,
)
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
        self.transaction_runner: TransactionRunner = DirectTransactionRunner()

    async def recover(self) -> None:
        await self.transaction_runner.run(self.recover_transaction)

    async def recover_transaction(self) -> None:
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
                except TransactionRetriesExhausted:
                    logger.warning("worker_poll_transaction_conflict")
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=0.1)
                except TimeoutError:
                    continue
            task: asyncio.Task[None]
            for task in self.active.values():
                task.cancel()

    async def dispatch(self, group: asyncio.TaskGroup) -> None:
        pending: list[PendingRun] = await self.transaction_runner.run(self.pending)
        run: PendingRun
        for run in pending:
            try:
                await self.dispatch_run(group, run)
            except TransactionRetriesExhausted:
                logger.warning("run_recovery_transaction_conflict run_id=%s", run.id)

    async def pending(self) -> list[PendingRun]:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            return await store.queries.pending()

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
        run: RunView = await self.transaction_runner.run(
            partial(self.finish_transaction, run_id, status, error)
        )
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

    async def finish_transaction(
        self, run_id: UUID, status: RunStatus, error: RunErrorCode | None
    ) -> RunView:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            return await store.set_status(run_id, status, error)

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
        except StoredDataCorrupt:
            await self.safe_finish(run_id, RunStatus.FAILED, RunErrorCode.STORED_DATA_CORRUPT)
        except TransactionRetriesExhausted:
            await self.safe_finish(run_id, RunStatus.FAILED, RunErrorCode.TRANSACTION_CONFLICT)
        except StorageUnavailable:
            logger.warning("run_database_unavailable run_id=%s", run_id)
        finally:
            self.active.pop(run_id, None)

    async def safe_finish(
        self, run_id: UUID, status: RunStatus, error: RunErrorCode | None
    ) -> None:
        try:
            await self.finish(run_id, status, error)
        except (StorageUnavailable, TransactionRetriesExhausted):
            logger.warning("run_status_pending run_id=%s", run_id)

    async def claim(self, run_id: UUID) -> ChatSnapshot | None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            run: RunView = await store.queries.get_run(run_id)
            if run.status != RunStatus.QUEUED:
                return None
            claimed: RunView = await store.set_status(run_id, RunStatus.RUNNING)
            if claimed.status != RunStatus.RUNNING:
                return None
            return await store.queries.snapshot(run.chat_id)

    async def generate(self, run_id: UUID) -> None:
        snapshot: ChatSnapshot | None = await self.transaction_runner.run(
            partial(self.claim, run_id)
        )
        if snapshot is None:
            return
        discussion: PreparedDiscussion | None = (
            await self.discussion_context.prepare(snapshot.chat.id)
            if self.discussion_context is not None
            else None
        )
        prefix: list[MessageView] = discussion.messages if discussion is not None else []
        messages: list[MessageView] = await asyncio.to_thread(
            select_context,
            discussion.model_history(snapshot.messages)
            if discussion is not None
            else snapshot.messages,
            self.generation_policy.input_budget,
            self.chat_token_counter,
            prefix,
        )
        retries: AsyncRetrying = self.generation_policy.retrying(partial(self.can_retry, run_id))
        await retries(
            self.consume,
            run_id,
            messages,
            discussion.references if discussion is not None else None,
        )
        await self.finish(run_id, RunStatus.COMPLETED)

    async def can_retry(self, run_id: UUID, error: BaseException) -> bool:
        if not isinstance(error, GenerationFailure) or not error.retryable:
            return False
        store: ChatStore
        async with self.chat_store_context.open() as store:
            current: RunView = await store.queries.get_run(run_id)
        return not current.content

    async def consume(
        self, run_id: UUID, messages: list[MessageView], references: Mapping[str, str] | None = None
    ) -> None:
        finish: str | None = None
        has_text: bool = False
        citations: DiscussionCitationStream = DiscussionCitationStream(references)
        chunks: AsyncIterator[Chunk]
        async with self.llm.stream(messages) as chunks:
            chunk: Chunk
            async for chunk in chunks:
                has_text = has_text or bool(chunk.text.strip())
                finish = chunk.finish or finish
                text: str = citations.feed(chunk.text)
                if text:
                    await self.flush(run_id, text)
        remaining: str = citations.feed("", final=True)
        if remaining:
            await self.flush(run_id, remaining)
        if not has_text:
            raise GenerationFailure(RunErrorCode.EMPTY_RESPONSE)
        if finish != "stop":
            raise GenerationFailure(RunErrorCode.INCOMPLETE_RESPONSE)

    async def flush(self, run_id: UUID, text: str) -> None:
        await self.transaction_runner.run(partial(self.append_transaction, run_id, text))

    async def append_transaction(self, run_id: UUID, text: str) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            if not await store.append(run_id, text):
                raise asyncio.CancelledError

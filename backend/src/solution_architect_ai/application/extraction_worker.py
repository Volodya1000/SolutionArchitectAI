import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.document_errors import DocumentFailure
from solution_architect_ai.application.errors import Conflict, StorageUnavailable
from solution_architect_ai.application.extraction_errors import ContextTooLarge
from solution_architect_ai.application.extraction_models import ExtractionView
from solution_architect_ai.application.extraction_ports import (
    ExtractionGraph,
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.structured_errors import StructuredGenerationFailure
from solution_architect_ai.domain.runs import RunStatus

logger: logging.Logger = logging.getLogger(__name__)


def failure_code(
    error: StructuredGenerationFailure
    | ContextTooLarge
    | TimeoutError
    | DocumentFailure
    | Conflict,
) -> str:
    if isinstance(error, StructuredGenerationFailure):
        return error.reason.value
    if isinstance(error, ContextTooLarge):
        return "context_too_large"
    if isinstance(error, TimeoutError):
        return "deadline_exceeded"
    return str(error)


class ExtractionWorker:
    def __init__(
        self,
        stores: ExtractionStoreFactory,
        graph: ExtractionGraph,
        capacity: GenerationCapacity,
        deadline: float,
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.graph: ExtractionGraph = graph
        self.capacity: GenerationCapacity = capacity
        self.deadline: float = deadline
        self.active: dict[UUID, asyncio.Task[None]] = {}
        self.stopping: asyncio.Event = asyncio.Event()

    async def finish(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> RunStatus | None:
        store: ExtractionStore
        try:
            async with self.stores.open() as store:
                if status == RunStatus.CANCELLED:
                    await store.set_status(run_id, RunStatus.CANCELLING)
                return (await store.set_status(run_id, status, error)).status
        except StorageUnavailable:
            logger.warning("extraction_status_pending run_id=%s", run_id)
            return None

    async def execute(self, run_id: UUID) -> None:
        try:
            if await self.finish(run_id, RunStatus.RUNNING) != RunStatus.RUNNING:
                return
            await self.run_graph(run_id)
        except asyncio.CancelledError:
            if not self.stopping.is_set():
                await self.finish(run_id, RunStatus.CANCELLED)
            raise
        except (
            StructuredGenerationFailure,
            ContextTooLarge,
            TimeoutError,
            DocumentFailure,
            Conflict,
        ) as error:
            await self.finish(run_id, RunStatus.FAILED, failure_code(error))
        except StorageUnavailable:
            logger.warning("extraction_database_unavailable run_id=%s", run_id)
        finally:
            self.active.pop(run_id, None)

    async def run_graph(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            view: ExtractionView = await store.get(run_id)
        elapsed: float = (datetime.now(UTC) - view.created_at).total_seconds()
        async with asyncio.timeout(max(0, self.deadline - elapsed)), self.capacity.slots:
            await self.graph.run(run_id)

    async def dispatch(self, group: asyncio.TaskGroup) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            pending: list[ExtractionView] = await store.pending()
        for run in pending:
            await self.dispatch_run(group, run)

    async def dispatch_run(self, group: asyncio.TaskGroup, run: ExtractionView) -> None:
        active: asyncio.Task[None] | None = self.active.get(run.id)
        if active is not None:
            if run.status == RunStatus.CANCELLING:
                active.cancel()
        elif run.status == RunStatus.CANCELLING:
            await self.finish(run.id, RunStatus.CANCELLED)
        elif not self.active:
            self.active[run.id] = group.create_task(self.execute(run.id))

    async def serve(self) -> None:
        group: asyncio.TaskGroup
        async with asyncio.TaskGroup() as group:
            while not self.stopping.is_set():
                await self.poll(group)
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=0.15)
                except TimeoutError:
                    continue
            for task in self.active.values():
                task.cancel()

    async def poll(self, group: asyncio.TaskGroup) -> None:
        try:
            await self.dispatch(group)
        except StorageUnavailable:
            logger.warning("extraction_database_unavailable")

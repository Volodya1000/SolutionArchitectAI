import asyncio
import logging
from uuid import UUID

from solution_architect_ai.application.capacity import GenerationCapacity
from solution_architect_ai.application.errors.chat_errors import Conflict, StorageUnavailable
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.errors.extraction_errors import (
    ExtractionError,
    StoredExtractionCorrupt,
)
from solution_architect_ai.application.errors.extraction_failure_mapper import (
    extraction_failure_code,
)
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStore,
    ClarificationStoreFactory,
)
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionGraph,
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.domain.runs import RunStatus

logger: logging.Logger = logging.getLogger(__name__)


class ExtractionWorker:
    def __init__(
        self,
        stores: ExtractionStoreFactory,
        graph: ExtractionGraph,
        capacity: GenerationCapacity,
        deadline: float,
        clarifications: ClarificationStoreFactory | None = None,
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.graph: ExtractionGraph = graph
        self.capacity: GenerationCapacity = capacity
        self.deadline: float = deadline
        self.active: dict[UUID, asyncio.Task[None]] = {}
        self.stopping: asyncio.Event = asyncio.Event()
        self.clarifications: ClarificationStoreFactory | None = clarifications
        self.recovered: bool = False

    async def finish(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> RunStatus | None:
        store: ExtractionStore
        try:
            async with self.stores.open() as store:
                return (await store.set_status(run_id, status, error)).status
        except (StorageUnavailable, StoredExtractionCorrupt):
            logger.warning("extraction_status_pending run_id=%s", run_id)
            return None

    async def execute(self, run_id: UUID) -> None:
        try:
            status: RunStatus | None = await self.finish(run_id, RunStatus.RUNNING)
            if status not in {RunStatus.RUNNING, RunStatus.WAITING_INPUT, RunStatus.COMPLETED}:
                return
            await self.run_graph(run_id)
        except asyncio.CancelledError:
            await self.handle_cancellation(run_id)
            raise
        except Conflict as error:
            await self.handle_conflict(run_id, error)
        except (
            StructuredGenerationFailure,
            ExtractionError,
            TimeoutError,
            DocumentFailure,
        ) as error:
            await self.finish(run_id, RunStatus.FAILED, extraction_failure_code(error))
        except StorageUnavailable:
            logger.warning("extraction_database_unavailable run_id=%s", run_id)
        finally:
            self.active.pop(run_id, None)

    async def handle_cancellation(self, run_id: UUID) -> None:
        if not self.stopping.is_set():
            await self.finish(run_id, RunStatus.CANCELLED)

    async def handle_conflict(self, run_id: UUID, error: Conflict) -> None:
        if error.code != "extraction_already_running":
            await self.finish(run_id, RunStatus.FAILED, extraction_failure_code(error))

    async def run_graph(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            view: ExtractionView = await store.get(run_id)
        async with self.capacity.slots:
            if self.clarifications is None:
                async with asyncio.timeout(max(0, self.deadline - view.elapsed_seconds)):
                    await self.graph.run(run_id)
            else:
                await self.run_segment(run_id)

    async def run_segment(self, run_id: UUID) -> None:
        if self.clarifications is None:
            return
        store: ClarificationStore
        async with self.clarifications.open() as store:
            elapsed: float = await store.begin_segment(run_id)
        heartbeat: asyncio.Task[None] = asyncio.create_task(self.heartbeat(run_id))
        try:
            async with asyncio.timeout(max(0, self.deadline - elapsed)):
                await self.graph.run(run_id)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            async with self.clarifications.open() as store:
                await store.heartbeat(run_id, finish=True)

    async def heartbeat(self, run_id: UUID) -> None:
        if self.clarifications is None:
            return
        while True:
            await asyncio.sleep(1)
            store: ClarificationStore
            async with self.clarifications.open() as store:
                await store.heartbeat(run_id)

    async def dispatch(self, group: asyncio.TaskGroup) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            pending: list[ExtractionView] = await store.pending()
        run: ExtractionView
        for run in pending:
            await self.dispatch_run(group, run)

    async def dispatch_run(self, group: asyncio.TaskGroup, run: ExtractionView) -> None:
        active: asyncio.Task[None] | None = self.active.get(run.id)
        if active is not None:
            if run.status == RunStatus.CANCELLING:
                active.cancel()
        elif run.status == RunStatus.CANCELLING:
            await self.finish(run.id, RunStatus.CANCELLED)
        elif len(self.active) < self.capacity.concurrency:
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
            task: asyncio.Task[None]
            for task in self.active.values():
                task.cancel()

    async def poll(self, group: asyncio.TaskGroup) -> None:
        try:
            if not self.recovered:
                if self.clarifications is not None:
                    store: ClarificationStore
                    async with self.clarifications.open() as store:
                        await store.recover_waiting()
                self.recovered = True
            await self.dispatch(group)
        except StorageUnavailable:
            logger.warning("extraction_database_unavailable")

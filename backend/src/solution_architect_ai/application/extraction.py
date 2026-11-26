from uuid import UUID

from solution_architect_ai.application.documents import DocumentService
from solution_architect_ai.application.extraction_models import (
    ExtractionStart,
    ExtractionView,
    StoredModelProfile,
)
from solution_architect_ai.application.extraction_ports import (
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.domain.runs import RunStatus


class ExtractionService:
    def __init__(
        self,
        stores: ExtractionStoreFactory,
        documents: DocumentService,
        profile: StoredModelProfile,
        config_digest: str,
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.documents: DocumentService = documents
        self.profile: StoredModelProfile = profile
        self.config_digest: str = config_digest

    async def start(self, command: ExtractionStart) -> ExtractionView:
        command = command.model_copy(
            update={"version_ids": sorted(set(command.version_ids), key=str)}
        )
        for version_id in command.version_ids:
            await self.documents.version(version_id)
        store: ExtractionStore
        async with self.stores.open() as store:
            return await store.start(command, self.profile, self.config_digest)

    async def get(self, run_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return await store.get(run_id)

    async def list_runs(self) -> list[ExtractionView]:
        store: ExtractionStore
        async with self.stores.open() as store:
            return await store.list_runs()

    async def cancel(self, run_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return await store.set_status(run_id, RunStatus.CANCELLING)

from uuid import UUID

from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
    StoredModelProfile,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.domain.runs import RunStatus


class RequirementsExtractionService:
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
        version_id: UUID
        for version_id in command.version_ids:
            await self.documents.get_version(version_id)
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.describe(await store.start(command, self.profile, self.config_digest))

    async def get(self, run_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.describe(await store.get(run_id))

    async def list_runs(self) -> list[ExtractionView]:
        store: ExtractionStore
        async with self.stores.open() as store:
            return [self.describe(view) for view in await store.list_runs()]

    async def cancel(self, run_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.describe(await store.set_status(run_id, RunStatus.CANCELLING))

    def describe(self, view: ExtractionView) -> ExtractionView:
        return view.model_copy(
            update={
                "configuration_current": (
                    view.model_profile == self.profile
                    and view.prompt_version == PROMPT_VERSION
                    and view.contract_version == CONTRACT_VERSION
                )
            }
        )

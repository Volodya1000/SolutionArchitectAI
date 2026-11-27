from uuid import UUID

from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    ExtractionHistory,
    ExtractionMatches,
    ExtractionStart,
    ExtractionSummary,
    ExtractionView,
    StoredExtractionMatches,
    StoredExtractionSummary,
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

    async def get_operation(self, operation_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.describe(await store.get_operation(operation_id))

    async def get_status(self, run_id: UUID) -> ExtractionSummary:
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.summarize(await store.get_status(run_id))

    async def get_matching(
        self,
        version_ids: list[UUID],
        analysis_scope: str,
        history: AnswerHistorySelection | None = None,
    ) -> ExtractionMatches:
        store: ExtractionStore
        async with self.stores.open() as store:
            matches: StoredExtractionMatches = await store.get_matching(
                version_ids, analysis_scope, self.profile, history
            )
        return ExtractionMatches(
            active=self.summarize(matches.active) if matches.active is not None else None,
            current_completed=self.summarize(matches.current_completed)
            if matches.current_completed is not None
            else None,
            latest_completed=self.summarize(matches.latest_completed)
            if matches.latest_completed is not None
            else None,
        )

    async def list_history(self, *, limit: int, offset: int) -> ExtractionHistory:
        store: ExtractionStore
        async with self.stores.open() as store:
            rows: list[StoredExtractionSummary] = await store.list_history(
                limit=limit, offset=offset
            )
        return ExtractionHistory(
            items=[self.summarize(row) for row in rows[:limit]], has_more=len(rows) > limit
        )

    def summarize(self, view: StoredExtractionSummary) -> ExtractionSummary:
        return ExtractionSummary.model_validate(
            view.model_dump(exclude={"model_profile", "contract_version", "prompt_version"})
        ).model_copy(update={"configuration_current": self.configuration_current(view)})

    def configuration_current(self, view: StoredExtractionSummary) -> bool:
        return (
            view.model_profile == self.profile
            and view.prompt_version == PROMPT_VERSION
            and view.contract_version == CONTRACT_VERSION
        )

    async def cancel(self, run_id: UUID) -> ExtractionView:
        store: ExtractionStore
        async with self.stores.open() as store:
            return self.describe(await store.set_status(run_id, RunStatus.CANCELLING))

    def describe(self, view: ExtractionView) -> ExtractionView:
        return view.model_copy(update={"configuration_current": (self.configuration_current(view))})

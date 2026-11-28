from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from uuid import UUID, uuid4

from dishka import AsyncContainer, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.extraction_resources import ExtractionResources
from backend.test_helpers.sql_store_setup import SqlStoreSetup, clarification_store_setup
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.protocols.document_protocols import DocumentStore
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.documents import DocumentProvider
from solution_architect_ai.di.extraction import ExtractionProvider
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.models import TaskRow
from solution_architect_ai.persistence.store_context import SqlAlchemyStoreContext


class ContinuationDocumentProvider(DocumentProvider):
    def __init__(self, task_id: UUID) -> None:
        self.continuation_task_id: UUID = task_id
        super().__init__()

    @provide(scope=Scope.APP)
    def document_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession]
    ) -> StoreContext[DocumentStore]:
        return SqlAlchemyStoreContext(
            database_sessions, partial(SqlAlchemyDocumentStore, task_id=self.continuation_task_id)
        )


class ContinuationExtractionProvider(ExtractionProvider):
    def __init__(self, task_id: UUID) -> None:
        self.continuation_task_id: UUID = task_id
        super().__init__()

    @provide(scope=Scope.APP)
    def actor_context(self, settings: Settings) -> ActorContext:
        actor: ActorContext = super().actor_context(settings)
        return replace(actor, task_id=self.continuation_task_id)

    @provide(scope=Scope.APP)
    def extraction_policy(self, settings: Settings) -> ExtractionPolicy:
        policy: ExtractionPolicy = super().extraction_policy(settings)
        return replace(policy, task_id=self.continuation_task_id)

    @provide(scope=Scope.APP)
    def extraction_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession]
    ) -> StoreContext[ExtractionStore]:
        return SqlAlchemyStoreContext(
            database_sessions, partial(SqlAlchemyExtractionStore, task_id=self.continuation_task_id)
        )


@dataclass(frozen=True)
class ContinuationResources:
    resources: ExtractionResources
    stores: SqlStoreSetup[SqlAlchemyClarificationStore]
    ambient_pending: list[UUID]


@asynccontextmanager
async def isolated_continuation_resources(
    original: ExtractionResources, stores: SqlStoreSetup[SqlAlchemyClarificationStore]
) -> AsyncGenerator[ContinuationResources]:
    task_id: UUID = uuid4()
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        owner: TaskRow | None = await store.session.get(TaskRow, stores.actor.task_id)
        assert owner is not None
        store.session.add(
            TaskRow(
                id=task_id, project_id=owner.project_id, title="Isolated continuation regression"
            )
        )
    extraction_store: ExtractionStore
    async with original.stores.open() as extraction_store:
        ambient_pending: list[UUID] = [item.id for item in await extraction_store.pending()]
    container: AsyncContainer = make_async_container(
        AppProvider(),
        ContinuationDocumentProvider(task_id),
        ContinuationExtractionProvider(task_id),
        context={Settings: original.settings},
    )
    resources: ExtractionResources = ExtractionResources(
        container,
        original.settings,
        await container.get(DocumentService),
        await container.get(StoreContext[ExtractionStore]),
        await container.get(RequirementsExtractionService),
        [],
    )
    scoped_stores: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        await container.get(async_sessionmaker[AsyncSession]), await container.get(ActorContext)
    )
    try:
        yield ContinuationResources(resources, scoped_stores, ambient_pending)
    finally:
        async with resources.stores.open() as extraction_store:
            run_id: UUID
            for run_id in resources.runs:
                view: ExtractionView = await extraction_store.get(run_id)
                if not view.status.terminal:
                    await extraction_store.set_status(run_id, RunStatus.FAILED, "test_cleanup")
        await container.close()

from functools import partial

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.protocols.clarification_protocols import ClarificationStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID
from solution_architect_ai.persistence.store_context import SqlAlchemyStoreContext


class ClarificationProvider(Provider):
    @provide(scope=Scope.APP)
    def actor_context(self, settings: Settings) -> ActorContext:
        return ActorContext(
            settings.local_actor.id,
            settings.local_actor.name,
            DEFAULT_TASK_ID,
            settings.local_actor.can_write,
        )

    @provide(scope=Scope.APP)
    def clarification_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession], actor: ActorContext
    ) -> StoreContext[ClarificationStore]:
        return SqlAlchemyStoreContext(
            database_sessions, partial(SqlAlchemyClarificationStore, actor=actor)
        )

    @provide(scope=Scope.APP)
    def clarification_service(
        self,
        clarification_store_context: StoreContext[ClarificationStore],
        documents_service: DocumentService,
    ) -> ClarificationService:
        return ClarificationService(clarification_store_context, documents_service)

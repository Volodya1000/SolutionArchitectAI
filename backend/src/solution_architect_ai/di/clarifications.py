from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStoreFactory,
)
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.persistence.clarifications.clarification_factory import (
    SqlAlchemyClarificationStoreFactory,
)
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


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
    def clarification_stores(
        self, engine: AsyncEngine, actor: ActorContext
    ) -> ClarificationStoreFactory:
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )
        return SqlAlchemyClarificationStoreFactory(sessions, actor)

    @provide(scope=Scope.APP)
    def clarification_service(
        self, stores: ClarificationStoreFactory, documents: DocumentService
    ) -> ClarificationService:
        return ClarificationService(stores, documents)

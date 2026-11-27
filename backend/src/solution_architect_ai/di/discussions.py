from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.context.discussion_context_builder import (
    DiscussionContextBuilder,
)
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.protocols.discussion_protocols import (
    DiscussionContext,
    DiscussionStoreFactory,
)
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.persistence.discussions.factory import SqlAlchemyDiscussionStoreFactory


class DiscussionProvider(Provider):
    @provide(scope=Scope.APP)
    def discussion_stores(self, engine: AsyncEngine, actor: ActorContext) -> DiscussionStoreFactory:
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )
        return SqlAlchemyDiscussionStoreFactory(sessions, actor)

    @provide(scope=Scope.APP)
    def discussion_service(
        self,
        stores: DiscussionStoreFactory,
        documents: DocumentService,
        clarifications: ClarificationService,
    ) -> DiscussionService:
        return DiscussionService(stores, documents, clarifications)

    @provide(scope=Scope.APP)
    def discussion_context(self, discussions: DiscussionService) -> DiscussionContext:
        return DiscussionContextBuilder(discussions)

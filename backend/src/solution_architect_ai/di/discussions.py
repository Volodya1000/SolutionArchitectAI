from functools import partial

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.context.discussion_context_builder import (
    DiscussionContextBuilder,
)
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.protocols.discussion_protocols import (
    DiscussionContext,
    DiscussionStore,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.store_context import SqlAlchemyStoreContext


class DiscussionProvider(Provider):
    @provide(scope=Scope.APP)
    def discussion_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession], actor: ActorContext
    ) -> StoreContext[DiscussionStore]:
        return SqlAlchemyStoreContext(
            database_sessions, partial(SqlAlchemyDiscussionStore, actor=actor)
        )

    @provide(scope=Scope.APP)
    def discussion_service(
        self,
        discussion_store_context: StoreContext[DiscussionStore],
        documents_service: DocumentService,
        clarification_service: ClarificationService,
    ) -> DiscussionService:
        return DiscussionService(discussion_store_context, documents_service, clarification_service)

    @provide(scope=Scope.APP)
    def discussion_context(self, discussion_service: DiscussionService) -> DiscussionContext:
        return DiscussionContextBuilder(discussion_service)

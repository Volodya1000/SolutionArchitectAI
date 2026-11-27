from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID
from solution_architect_ai.persistence.store import SqlAlchemyStore
from solution_architect_ai.persistence.store_context import (
    SqlAlchemyStoreContext,
    SqlStoreErrorPolicy,
)


@dataclass(frozen=True)
class SqlStoreSetup[StoreT]:
    context: SqlAlchemyStoreContext[StoreT]
    sessions: async_sessionmaker[AsyncSession]
    actor: ActorContext

    def open(self) -> AbstractAsyncContextManager[StoreT]:
        return self.context.open()


def chat_store_setup(sessions: async_sessionmaker[AsyncSession]) -> SqlStoreSetup[SqlAlchemyStore]:
    return SqlStoreSetup(
        SqlAlchemyStoreContext(sessions, SqlAlchemyStore),
        sessions,
        ActorContext.local(DEFAULT_TASK_ID),
    )


def document_store_setup(
    sessions: async_sessionmaker[AsyncSession], *, task_id: UUID = DEFAULT_TASK_ID
) -> SqlStoreSetup[SqlAlchemyDocumentStore]:
    return SqlStoreSetup(
        SqlAlchemyStoreContext(
            sessions,
            partial(SqlAlchemyDocumentStore, task_id=task_id),
            SqlStoreErrorPolicy.DOCUMENT,
        ),
        sessions,
        ActorContext.local(task_id),
    )


def extraction_store_setup(
    sessions: async_sessionmaker[AsyncSession], *, task_id: UUID = DEFAULT_TASK_ID
) -> SqlStoreSetup[SqlAlchemyExtractionStore]:
    return SqlStoreSetup(
        SqlAlchemyStoreContext(
            sessions,
            partial(SqlAlchemyExtractionStore, task_id=task_id),
            SqlStoreErrorPolicy.EXTRACTION,
        ),
        sessions,
        ActorContext.local(task_id),
    )


def clarification_store_setup(
    sessions: async_sessionmaker[AsyncSession], actor: ActorContext
) -> SqlStoreSetup[SqlAlchemyClarificationStore]:
    return SqlStoreSetup(
        SqlAlchemyStoreContext(sessions, partial(SqlAlchemyClarificationStore, actor=actor)),
        sessions,
        actor,
    )


def discussion_store_setup(
    sessions: async_sessionmaker[AsyncSession], actor: ActorContext
) -> SqlStoreSetup[SqlAlchemyDiscussionStore]:
    return SqlStoreSetup(
        SqlAlchemyStoreContext(sessions, partial(SqlAlchemyDiscussionStore, actor=actor)),
        sessions,
        actor,
    )

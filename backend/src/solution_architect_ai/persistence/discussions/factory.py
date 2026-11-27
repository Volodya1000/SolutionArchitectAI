import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore


class SqlAlchemyDiscussionStoreFactory:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], actor: ActorContext) -> None:
        self.sessions: async_sessionmaker[AsyncSession] = sessions
        self.actor: ActorContext = actor

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[SqlAlchemyDiscussionStore]:
        try:
            session: AsyncSession
            async with asyncio.timeout(5), self.sessions() as session, session.begin():
                yield SqlAlchemyDiscussionStore(session, self.actor)
        except (SQLAlchemyError, TimeoutError):
            raise StorageUnavailable("database_unavailable") from None

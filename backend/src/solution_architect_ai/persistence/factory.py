import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.contracts import StorageUnavailable
from solution_architect_ai.application.ports import ChatStore
from solution_architect_ai.persistence.store import SqlAlchemyStore


class SqlAlchemyStoreFactory:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ChatStore]:
        try:
            async with asyncio.timeout(5), self.sessions() as session, session.begin():
                yield SqlAlchemyStore(session)
        except (SQLAlchemyError, TimeoutError):
            raise StorageUnavailable("database_unavailable") from None

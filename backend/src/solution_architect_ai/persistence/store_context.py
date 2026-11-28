import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import psycopg
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable


def database_unavailable(
    error: DBAPIError | PoolTimeoutError | TimeoutError, *, scope_expired: bool
) -> bool:
    if isinstance(error, PoolTimeoutError):
        return True
    if isinstance(error, TimeoutError):
        return scope_expired
    if error.connection_invalidated:
        return True
    original: Exception | None = error.orig
    if not isinstance(original, psycopg.OperationalError):
        return False
    state: str | None = original.sqlstate
    return state is None or state.startswith("08") or state in {"53300", "57P01", "57P02", "57P03"}


class SqlAlchemyStoreContext[StoreT]:
    def __init__(
        self,
        database_sessions: async_sessionmaker[AsyncSession],
        store_constructor: Callable[[AsyncSession], StoreT],
    ) -> None:
        self.database_sessions: async_sessionmaker[AsyncSession] = database_sessions
        self.store_constructor: Callable[[AsyncSession], StoreT] = store_constructor

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[StoreT]:
        timeout: asyncio.Timeout = asyncio.timeout(5)
        try:
            session: AsyncSession
            async with timeout, self.database_sessions() as session, session.begin():
                yield self.store_constructor(session)
        except (DBAPIError, PoolTimeoutError, TimeoutError) as error:
            if not database_unavailable(error, scope_expired=timeout.expired()):
                raise
            raise StorageUnavailable("database_unavailable") from None

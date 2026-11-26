import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors import StorageUnavailable
from solution_architect_ai.application.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.extraction_ports import ExtractionStore
from solution_architect_ai.persistence.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


class SqlAlchemyExtractionStoreFactory:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, task_id: UUID = DEFAULT_TASK_ID
    ) -> None:
        self.sessions: async_sessionmaker[AsyncSession] = sessions
        self.task_id: UUID = task_id

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ExtractionStore]:
        try:
            session: AsyncSession
            async with asyncio.timeout(5), self.sessions() as session, session.begin():
                yield SqlAlchemyExtractionStore(session, task_id=self.task_id)
        except (SQLAlchemyError, TimeoutError):
            raise StorageUnavailable("database_unavailable") from None
        except ValidationError:
            raise StoredExtractionCorrupt("stored_extraction_corrupt") from None

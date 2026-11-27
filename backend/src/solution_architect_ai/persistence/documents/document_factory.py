import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.protocols.document_protocols import DocumentStore
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


class SqlAlchemyDocumentStoreFactory:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, task_id: UUID = DEFAULT_TASK_ID
    ) -> None:
        self.sessions: async_sessionmaker[AsyncSession] = sessions
        self.task_id: UUID = task_id

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[DocumentStore]:
        try:
            session: AsyncSession
            async with asyncio.timeout(5), self.sessions() as session, session.begin():
                yield SqlAlchemyDocumentStore(session, task_id=self.task_id)
        except ValidationError:
            raise DocumentFailure(DocumentErrorCode.CORRUPT_METADATA) from None
        except (SQLAlchemyError, TimeoutError):
            raise StorageUnavailable("database_unavailable") from None

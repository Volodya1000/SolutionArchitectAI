import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from enum import Enum

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt


class SqlStoreErrorPolicy(Enum):
    STORAGE = "storage"
    DOCUMENT = "document"
    EXTRACTION = "extraction"

    def translate(self, error: SQLAlchemyError | TimeoutError | ValidationError) -> Exception:
        if not isinstance(error, ValidationError):
            return StorageUnavailable("database_unavailable")
        if self is SqlStoreErrorPolicy.DOCUMENT:
            return DocumentFailure(DocumentErrorCode.CORRUPT_METADATA)
        if self is SqlStoreErrorPolicy.EXTRACTION:
            return StoredExtractionCorrupt("stored_extraction_corrupt")
        return error


class SqlAlchemyStoreContext[StoreT]:
    def __init__(
        self,
        database_sessions: async_sessionmaker[AsyncSession],
        store_constructor: Callable[[AsyncSession], StoreT],
        error_policy: SqlStoreErrorPolicy = SqlStoreErrorPolicy.STORAGE,
    ) -> None:
        self.database_sessions: async_sessionmaker[AsyncSession] = database_sessions
        self.store_constructor: Callable[[AsyncSession], StoreT] = store_constructor
        self.error_policy: SqlStoreErrorPolicy = error_policy

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[StoreT]:
        try:
            session: AsyncSession
            async with asyncio.timeout(5), self.database_sessions() as session, session.begin():
                yield self.store_constructor(session)
        except (SQLAlchemyError, TimeoutError, ValidationError) as error:
            translated: Exception = self.error_policy.translate(error)
            if translated is error:
                raise
            raise translated from None

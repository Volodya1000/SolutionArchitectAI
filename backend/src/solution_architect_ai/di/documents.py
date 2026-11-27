from functools import partial

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solution_architect_ai.application.protocols.document_protocols import (
    DocumentParser,
    DocumentStore,
    FileStorage,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.infrastructure.parsers.document_parser import (
    DocumentParser as FormatDocumentParser,
)
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID
from solution_architect_ai.persistence.store_context import (
    SqlAlchemyStoreContext,
    SqlStoreErrorPolicy,
)


class DocumentProvider(Provider):
    @provide(scope=Scope.APP)
    def document_store_context(
        self, database_sessions: async_sessionmaker[AsyncSession]
    ) -> StoreContext[DocumentStore]:
        return SqlAlchemyStoreContext(
            database_sessions,
            partial(SqlAlchemyDocumentStore, task_id=DEFAULT_TASK_ID),
            SqlStoreErrorPolicy.DOCUMENT,
        )

    @provide(scope=Scope.APP)
    def files_storage(self, settings: Settings) -> FileStorage:
        return LocalFileStorage(settings.storage.root)

    @provide(scope=Scope.APP)
    def document_parser(self) -> DocumentParser:
        return FormatDocumentParser()

    @provide(scope=Scope.APP)
    def document_service(
        self,
        document_store_context: StoreContext[DocumentStore],
        files_storage: FileStorage,
        document_parser: DocumentParser,
    ) -> DocumentService:
        return DocumentService(document_store_context, files_storage, document_parser)

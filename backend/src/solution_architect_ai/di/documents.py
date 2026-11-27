from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.protocols.document_protocols import (
    DocumentParser,
    DocumentStoreFactory,
    FileStorage,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.infrastructure.parsers.document_parser import (
    DocumentParser as FormatDocumentParser,
)
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.documents.document_factory import (
    SqlAlchemyDocumentStoreFactory,
)


class DocumentProvider(Provider):
    @provide(scope=Scope.APP)
    def document_stores(self, engine: AsyncEngine) -> DocumentStoreFactory:
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False
        )
        return SqlAlchemyDocumentStoreFactory(sessions)

    @provide(scope=Scope.APP)
    def files_storage(self, settings: Settings) -> FileStorage:
        return LocalFileStorage(settings.storage.root)

    @provide(scope=Scope.APP)
    def document_parser(self) -> DocumentParser:
        return FormatDocumentParser()

    @provide(scope=Scope.APP)
    def document_service(
        self,
        stores: DocumentStoreFactory,
        files_storage: FileStorage,
        document_parser: DocumentParser,
    ) -> DocumentService:
        return DocumentService(stores, files_storage, document_parser)

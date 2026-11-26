from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.document_ports import (
    DocumentParser,
    DocumentStoreFactory,
    FileStorage,
)
from solution_architect_ai.application.documents import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.infrastructure.document_parser import (
    DocumentParser as FormatDocumentParser,
)
from solution_architect_ai.infrastructure.files import LocalFileStorage
from solution_architect_ai.persistence.document_factory import SqlAlchemyDocumentStoreFactory


class DocumentProvider(Provider):
    @provide(scope=Scope.APP)
    def document_stores(self, engine: AsyncEngine) -> DocumentStoreFactory:
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False
        )
        return SqlAlchemyDocumentStoreFactory(sessions)

    @provide(scope=Scope.APP)
    def files(self, settings: Settings) -> FileStorage:
        return LocalFileStorage(settings.storage.root)

    @provide(scope=Scope.APP)
    def parser(self) -> DocumentParser:
        return FormatDocumentParser()

    @provide(scope=Scope.APP)
    def document_service(
        self, stores: DocumentStoreFactory, files: FileStorage, parser: DocumentParser
    ) -> DocumentService:
        return DocumentService(stores, files, parser)

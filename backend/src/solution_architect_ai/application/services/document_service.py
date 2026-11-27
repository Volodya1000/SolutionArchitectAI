import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
    DocumentView,
    StoredParse,
    UploadDocument,
    UploadOperationView,
    UploadStage,
)
from solution_architect_ai.application.protocols.document_protocols import (
    DocumentParser,
    DocumentStore,
    FileStorage,
    StagedFile,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_identity import parse_digest, upload_digest
from solution_architect_ai.domain.documents import ParsedDocument


class DocumentService:
    def __init__(
        self,
        document_store_context: StoreContext[DocumentStore],
        files_storage: FileStorage,
        document_parser: DocumentParser,
    ) -> None:
        self.document_store_context: StoreContext[DocumentStore] = document_store_context
        self.files_storage: FileStorage = files_storage
        self.document_parser: DocumentParser = document_parser

    async def upload(
        self, command: UploadDocument, chunks: AsyncIterator[bytes]
    ) -> DocumentVersionView:
        staged_file: StagedFile = await self.files_storage.stage(chunks)
        try:
            content: bytes = await self.files_storage.staged_content(staged_file)
            mime: str = await asyncio.to_thread(
                self.document_parser.validate, content, command.filename, command.mime_type
            )
            normalized: UploadDocument = command.model_copy(update={"mime_type": mime})
            digest: str = upload_digest(normalized, staged_file)
            store: DocumentStore
            async with self.document_store_context.open() as store:
                operation: UploadOperationView = await store.prepare(
                    normalized, staged_file.size, staged_file.sha256, digest
                )
            await self.files_storage.publish(staged_file, operation.version.storage_key)
            async with self.document_store_context.open() as store:
                return await store.complete(command.operation_id)
        finally:
            await self.files_storage.discard(staged_file)

    async def list_documents(self) -> list[DocumentView]:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.list_documents()

    async def list_versions(self, file_id: UUID) -> list[DocumentVersionView]:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.list_versions(file_id)

    async def get_version(self, version_id: UUID) -> DocumentVersionView:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.get_version(version_id)

    async def read(self, version_id: UUID) -> bytes:
        _version: DocumentVersionView
        content: bytes
        _version, content = await self._load_version_content(version_id)
        return content

    async def _load_version_content(self, version_id: UUID) -> tuple[DocumentVersionView, bytes]:
        version: DocumentVersionView = await self.get_version(version_id)
        content: bytes = await self.files_storage.read(
            version.storage_key, version.size, version.sha256
        )
        return version, content

    async def get_parsed_document(self, version_id: UUID) -> ParsedDocument:
        version: DocumentVersionView
        content: bytes
        version, content = await self._load_version_content(version_id)
        store: DocumentStore
        async with self.document_store_context.open() as store:
            saved: StoredParse | None = await store.get_parse(version_id)
        if saved is None:
            parsed: ParsedDocument = await asyncio.to_thread(
                self.document_parser.parse,
                version.file_id,
                version_id,
                content,
                version.original_name,
                version.mime_type,
            )
            async with self.document_store_context.open() as store:
                saved = await store.save_parse(
                    StoredParse(document=parsed, digest=parse_digest(parsed))
                )
        if (
            parse_digest(saved.document) != saved.digest
            or saved.document.version_id != version_id
            or saved.document.file_id != version.file_id
            or saved.document.sha256 != version.sha256
        ):
            raise DocumentFailure(DocumentErrorCode.CORRUPT_PARSE)
        return saved.document

    async def get_upload_operation(self, operation_id: UUID) -> UploadOperationView:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.get_upload_operation(operation_id)

    async def recover_uploads(self) -> list[UploadOperationView]:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            pending: list[UploadOperationView] = await store.pending()
        results: list[UploadOperationView] = []
        operation: UploadOperationView
        for operation in pending:
            try:
                version: DocumentVersionView = operation.version
                await self.files_storage.read(version.storage_key, version.size, version.sha256)
                async with self.document_store_context.open() as store:
                    completed: DocumentVersionView = await store.complete(operation.operation_id)
                results.append(
                    operation.model_copy(
                        update={
                            "stage": UploadStage.COMPLETED,
                            "version": completed,
                            "diagnostic": None,
                        }
                    )
                )
            except DocumentFailure as error:
                results.append(operation.model_copy(update={"diagnostic": error.code.value}))
            except (StorageUnavailable, OSError, TimeoutError):
                results.append(
                    operation.model_copy(
                        update={"diagnostic": DocumentErrorCode.STORAGE_UNAVAILABLE.value}
                    )
                )
        return results

    async def attach_document(self, message_id: UUID, version_id: UUID) -> DocumentVersionView:
        await self.read(version_id)
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.attach_document(message_id, version_id)

    async def list_attachments(self, message_id: UUID) -> list[DocumentVersionView]:
        store: DocumentStore
        async with self.document_store_context.open() as store:
            return await store.list_attachments(message_id)

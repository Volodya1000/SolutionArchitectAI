import asyncio
import json
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import Final
from uuid import UUID

from pydantic import TypeAdapter

from solution_architect_ai.application.document_dto import (
    DocumentVersionView,
    DocumentView,
    StoredParse,
    UploadDocument,
    UploadOperationView,
)
from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.application.document_ports import (
    DocumentParser,
    DocumentStore,
    DocumentStoreFactory,
    FileStorage,
    StagedFile,
)
from solution_architect_ai.domain.documents import ParsedDocument

PARSED_DOCUMENT: Final[TypeAdapter[ParsedDocument]] = TypeAdapter(ParsedDocument)


def parse_digest(document: ParsedDocument) -> str:
    return sha256(PARSED_DOCUMENT.dump_json(document)).hexdigest()


class DocumentService:
    def __init__(
        self, stores: DocumentStoreFactory, files: FileStorage, parser: DocumentParser
    ) -> None:
        self.stores: DocumentStoreFactory = stores
        self.files: FileStorage = files
        self.parser: DocumentParser = parser

    async def upload(
        self, command: UploadDocument, chunks: AsyncIterator[bytes]
    ) -> DocumentVersionView:
        staged: StagedFile = await self.files.stage(chunks)
        try:
            content: bytes = await self.files.staged_content(staged)
            mime: str = await asyncio.to_thread(
                self.parser.validate, content, command.filename, command.mime_type
            )
            normalized: UploadDocument = command.model_copy(update={"mime_type": mime})
            payload: str = json.dumps(
                [str(command.file_id), command.filename, mime, staged.size, staged.sha256]
            )
            digest: str = sha256(payload.encode()).hexdigest()
            store: DocumentStore
            async with self.stores.open() as store:
                operation: UploadOperationView = await store.prepare(
                    normalized, staged.size, staged.sha256, digest
                )
            await self.files.publish(staged, operation.version.storage_key)
            async with self.stores.open() as store:
                return await store.complete(command.operation_id)
        finally:
            await self.files.discard(staged)

    async def list_documents(self) -> list[DocumentView]:
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.list_documents()

    async def versions(self, file_id: UUID) -> list[DocumentVersionView]:
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.versions(file_id)

    async def version(self, version_id: UUID) -> DocumentVersionView:
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.version(version_id)

    async def read(self, version_id: UUID) -> bytes:
        version: DocumentVersionView = await self.version(version_id)
        return await self.files.read(version.storage_key, version.size, version.sha256)

    async def parsed(self, version_id: UUID) -> ParsedDocument:
        version: DocumentVersionView = await self.version(version_id)
        content: bytes = await self.files.read(version.storage_key, version.size, version.sha256)
        store: DocumentStore
        async with self.stores.open() as store:
            saved: StoredParse | None = await store.get_parse(version_id)
        if saved is None:
            parsed: ParsedDocument = await asyncio.to_thread(
                self.parser.parse,
                version.file_id,
                version_id,
                content,
                version.original_name,
                version.mime_type,
            )
            async with self.stores.open() as store:
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

    async def operation(self, operation_id: UUID) -> UploadOperationView:
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.operation(operation_id)

    async def recover(self) -> list[UploadOperationView]:
        store: DocumentStore
        async with self.stores.open() as store:
            pending: list[UploadOperationView] = await store.pending()
        results: list[UploadOperationView] = []
        operation: UploadOperationView
        for operation in pending:
            try:
                version: DocumentVersionView = operation.version
                await self.files.read(version.storage_key, version.size, version.sha256)
                async with self.stores.open() as store:
                    await store.complete(operation.operation_id)
                    results.append(await store.operation(operation.operation_id))
            except DocumentFailure as error:
                results.append(operation.model_copy(update={"diagnostic": error.code.value}))
        return results

    async def attach(self, message_id: UUID, version_id: UUID) -> DocumentVersionView:
        await self.read(version_id)
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.attach(message_id, version_id)

    async def attachments(self, message_id: UUID) -> list[DocumentVersionView]:
        store: DocumentStore
        async with self.stores.open() as store:
            return await store.attachments(message_id)

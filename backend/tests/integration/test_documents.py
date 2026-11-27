import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.tests.sql_store_setup import document_store_setup
from solution_architect_ai.application.errors.chat_errors import (
    Conflict,
    Missing,
    StorageUnavailable,
)
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
    UploadDocument,
    UploadOperationView,
    UploadStage,
)
from solution_architect_ai.application.protocols.document_protocols import DocumentStore, StagedFile
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.documents.document_models import (
    DocumentUploadRow,
    ParsedDocumentRow,
)
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


@pytest.fixture(name="resources")
async def document_resources(
    tmp_path: Path,
) -> AsyncIterator[tuple[DocumentService, AsyncEngine, Path]]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: bootstrap()})
    try:
        engine: AsyncEngine = await container.get(AsyncEngine)
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False
        )
        factory: StoreContext[DocumentStore] = document_store_setup(sessions)
        yield (
            DocumentService(factory, LocalFileStorage(tmp_path, max_bytes=4096), DocumentParser()),
            engine,
            tmp_path,
        )
    finally:
        await container.close()


async def upload(
    service: DocumentService,
    content: bytes = b"The system shall retain records.",
    file_id: UUID | None = None,
) -> DocumentVersionView:
    return await service.upload(
        UploadDocument(
            operation_id=uuid4(), filename="brd.txt", mime_type="text/plain", file_id=file_id
        ),
        chunks(content),
    )


async def test_new_revision_keeps_original_and_parse_reproducible(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    first: DocumentVersionView = await upload(service)
    first_parse: ParsedDocument = await service.get_parsed_document(first.version_id)
    second: DocumentVersionView = await upload(
        service, b"The system shall retain records for seven days.", first.file_id
    )
    assert first.file_id == second.file_id
    assert first.version_id != second.version_id
    assert await service.read(first.version_id) == b"The system shall retain records."
    assert (
        await service.read(second.version_id) == b"The system shall retain records for seven days."
    )
    assert await service.get_parsed_document(first.version_id) == first_parse
    assert {version.version_id for version in await service.list_versions(first.file_id)} == {
        first.version_id,
        second.version_id,
    }


async def test_concurrent_upload_replay_and_new_versions_do_not_duplicate(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    command: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="brd.txt", mime_type="text/plain"
    )
    first: DocumentVersionView
    replay: DocumentVersionView
    first, replay = await asyncio.gather(
        service.upload(command, chunks(b"original")), service.upload(command, chunks(b"original"))
    )
    assert first == replay
    second: DocumentVersionView
    third: DocumentVersionView
    second, third = await asyncio.gather(
        upload(service, b"second", first.file_id), upload(service, b"third", first.file_id)
    )
    assert len({first.version_id, second.version_id, third.version_id}) == 3
    assert len(await service.list_versions(first.file_id)) == 3
    with pytest.raises(Conflict):
        await service.upload(command, chunks(b"different"))
    assert await service.read(first.version_id) == b"original"


async def test_missing_corrupt_and_wrong_scope_sources_never_substitute_latest(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    version: DocumentVersionView = await upload(service)
    await service.get_parsed_document(version.version_id)
    path: Path = resources[2] / version.storage_key
    await asyncio.to_thread(path.write_bytes, b"corrupt")
    with pytest.raises(DocumentFailure) as error:
        await service.get_parsed_document(version.version_id)
    assert error.value.code == DocumentErrorCode.CORRUPT_FILE
    await asyncio.to_thread(path.unlink)
    with pytest.raises(DocumentFailure) as missing:
        await service.read(version.version_id)
    assert missing.value.code == DocumentErrorCode.MISSING_FILE
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        resources[1], expire_on_commit=False
    )
    alien: StoreContext[DocumentStore] = document_store_setup(sessions, task_id=uuid4())
    store: DocumentStore
    async with alien.open() as store:
        with pytest.raises(Missing):
            await store.get_version(version.version_id)
        with pytest.raises(Missing):
            await store.list_versions(version.file_id)


async def test_recovery_registers_published_file_without_duplicate_version(
    resources: tuple[DocumentService, AsyncEngine, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service: DocumentService = resources[0]
    command: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="brd.txt", mime_type="text/plain"
    )
    original: Callable[[SqlAlchemyDocumentStore, UUID], Awaitable[DocumentVersionView]] = (
        SqlAlchemyDocumentStore.complete
    )

    async def fail_complete(
        _store: SqlAlchemyDocumentStore, _operation_id: UUID
    ) -> DocumentVersionView:
        raise StorageUnavailable("injected_commit_failure")

    monkeypatch.setattr(SqlAlchemyDocumentStore, "complete", fail_complete)
    with pytest.raises(StorageUnavailable):
        await service.upload(command, chunks(b"published before SQL outage"))
    pending: UploadOperationView = await service.get_upload_operation(command.operation_id)
    assert pending.stage == UploadStage.PREPARED
    monkeypatch.setattr(SqlAlchemyDocumentStore, "complete", original)
    await service.recover_uploads()
    restored: UploadOperationView = await service.get_upload_operation(command.operation_id)
    assert restored.stage == UploadStage.COMPLETED
    assert await service.read(restored.version.version_id) == b"published before SQL outage"
    await service.recover_uploads()
    assert len(await service.list_versions(restored.version.file_id)) == 1


async def test_saved_parse_corruption_is_explicit(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    version: DocumentVersionView = await upload(service)
    await service.get_parsed_document(version.version_id)
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](resources[1])
    session: AsyncSession
    async with sessions() as session, session.begin():
        await session.execute(
            update(ParsedDocumentRow)
            .where(ParsedDocumentRow.version_id == version.version_id)
            .values(digest="0" * 64)
        )
    with pytest.raises(DocumentFailure) as error:
        await service.get_parsed_document(version.version_id)
    assert error.value.code == DocumentErrorCode.CORRUPT_PARSE


async def test_malformed_saved_parse_json_has_a_typed_error(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    version: DocumentVersionView = await upload(service)
    await service.get_parsed_document(version.version_id)
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](resources[1])
    session: AsyncSession
    async with sessions() as session, session.begin():
        await session.execute(
            update(ParsedDocumentRow)
            .where(ParsedDocumentRow.version_id == version.version_id)
            .values(body="{")
        )
    with pytest.raises(DocumentFailure) as error:
        await service.get_parsed_document(version.version_id)
    assert error.value.code == DocumentErrorCode.CORRUPT_PARSE


async def test_malformed_upload_journal_metadata_has_a_typed_error(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    command: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="brd.txt", mime_type="text/plain"
    )
    await service.upload(command, chunks(b"Source requirement"))
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](resources[1])
    session: AsyncSession
    async with sessions() as session, session.begin():
        await session.execute(
            update(DocumentUploadRow)
            .where(DocumentUploadRow.operation_id == command.operation_id)
            .values(version_json="{")
        )
    with pytest.raises(DocumentFailure) as error:
        await service.get_upload_operation(command.operation_id)
    assert error.value.code == DocumentErrorCode.CORRUPT_METADATA


async def test_concurrent_parse_has_one_stable_fragment_set(
    resources: tuple[DocumentService, AsyncEngine, Path],
) -> None:
    service: DocumentService = resources[0]
    version: DocumentVersionView = await upload(service)
    first: ParsedDocument
    second: ParsedDocument
    first, second = await asyncio.gather(
        service.get_parsed_document(version.version_id),
        service.get_parsed_document(version.version_id),
    )
    assert first == second
    assert first.fragments


async def test_prepared_upload_without_published_file_is_diagnosed_and_retried(
    resources: tuple[DocumentService, AsyncEngine, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service: DocumentService = resources[0]
    command: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="brd.txt", mime_type="text/plain"
    )
    original: Callable[[LocalFileStorage, StagedFile, str], Awaitable[None]] = (
        LocalFileStorage.publish
    )

    async def fail_publish(_files: LocalFileStorage, _staged: StagedFile, _key: str) -> None:
        raise DocumentFailure(DocumentErrorCode.STORAGE_UNAVAILABLE)

    monkeypatch.setattr(LocalFileStorage, "publish", fail_publish)
    with pytest.raises(DocumentFailure):
        await service.upload(command, chunks(b"Prepared source"))
    diagnosed: list[UploadOperationView] = await service.recover_uploads()
    assert any(
        item.operation_id == command.operation_id
        and item.diagnostic == DocumentErrorCode.MISSING_FILE.value
        for item in diagnosed
    )
    monkeypatch.setattr(LocalFileStorage, "publish", original)
    version: DocumentVersionView = await service.upload(command, chunks(b"Prepared source"))
    assert await service.read(version.version_id) == b"Prepared source"
    assert len(await service.list_versions(version.file_id)) == 1


async def test_recovery_continues_after_one_database_failure(
    resources: tuple[DocumentService, AsyncEngine, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    service: DocumentService = resources[0]
    first: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="first.txt", mime_type="text/plain"
    )
    second: UploadDocument = UploadDocument(
        operation_id=uuid4(), filename="second.txt", mime_type="text/plain"
    )
    original: Callable[[SqlAlchemyDocumentStore, UUID], Awaitable[DocumentVersionView]] = (
        SqlAlchemyDocumentStore.complete
    )

    async def unavailable(
        _store: SqlAlchemyDocumentStore, _operation_id: UUID
    ) -> DocumentVersionView:
        raise StorageUnavailable("database_unavailable")

    monkeypatch.setattr(SqlAlchemyDocumentStore, "complete", unavailable)
    for command in (first, second):
        with pytest.raises(StorageUnavailable):
            await service.upload(command, chunks(b"Published document"))

    async def fail_first(store: SqlAlchemyDocumentStore, operation_id: UUID) -> DocumentVersionView:
        if operation_id == first.operation_id:
            raise StorageUnavailable("database_unavailable")
        return await original(store, operation_id)

    monkeypatch.setattr(SqlAlchemyDocumentStore, "complete", fail_first)
    recovered: list[UploadOperationView] = await service.recover_uploads()
    results: dict[UUID, UploadOperationView] = {item.operation_id: item for item in recovered}
    assert results[first.operation_id].diagnostic == DocumentErrorCode.STORAGE_UNAVAILABLE.value
    assert results[second.operation_id].stage == UploadStage.COMPLETED
    assert (
        await service.read(results[second.operation_id].version.version_id) == b"Published document"
    )

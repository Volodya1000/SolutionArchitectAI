import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, from_context, make_async_container
from dishka.dependency_source import CompositeDependencySource
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import ChatError
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.models.chat_dto import ChatSnapshot, ChatView, StartRun
from solution_architect_ai.application.models.document_dto import (
    DocumentErrorView,
    DocumentVersionView,
    DocumentView,
    UploadOperationView,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore
from solution_architect_ai.application.protocols.document_protocols import DocumentStoreFactory
from solution_architect_ai.application.services.document_identity import PARSED_DOCUMENT
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap, chat_error
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.documents.document_factory import (
    SqlAlchemyDocumentStoreFactory,
)
from solution_architect_ai.persistence.factory import SqlAlchemyStoreFactory
from solution_architect_ai.presentation.document_routes import document_error, router

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]
VERSIONS: Final[TypeAdapter[list[DocumentVersionView]]] = TypeAdapter(list[DocumentVersionView])
DOCUMENTS: Final[TypeAdapter[list[DocumentView]]] = TypeAdapter(list[DocumentView])


class ServiceProvider(Provider):
    service: CompositeDependencySource = from_context(DocumentService, scope=Scope.APP)


@pytest.fixture(name="client")
async def document_client(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, AsyncEngine]]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    infrastructure: AsyncContainer = make_async_container(
        AppProvider(), context={Settings: bootstrap()}
    )
    stack: AsyncExitStack
    async with AsyncExitStack() as stack:
        stack.push_async_callback(infrastructure.close)
        engine: AsyncEngine = await infrastructure.get(AsyncEngine)
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False
        )
        stores: DocumentStoreFactory = SqlAlchemyDocumentStoreFactory(sessions)
        service: DocumentService = DocumentService(
            stores, LocalFileStorage(tmp_path, max_bytes=4096), DocumentParser()
        )
        container: AsyncContainer = make_async_container(
            ServiceProvider(), context={DocumentService: service}
        )
        stack.push_async_callback(container.close)
        app: FastAPI = FastAPI()
        app.include_router(router)
        app.add_exception_handler(DocumentFailure, document_error)
        app.add_exception_handler(ChatError, chat_error)
        setup_dishka(container, app)
        http: httpx.AsyncClient
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield http, engine


async def new_document(http: httpx.AsyncClient) -> DocumentVersionView:
    response: httpx.Response = await http.post(
        "/api/documents",
        params={"operation_id": str(uuid4()), "filename": "brd.md"},
        content=b"# BRD\nThe system shall retain data.",
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 201
    return DocumentVersionView.model_validate_json(response.content, strict=True)


async def test_document_browser_contract_includes_versioned_parse_and_download(
    client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    http: httpx.AsyncClient = client[0]
    version: DocumentVersionView = await new_document(http)
    documents: httpx.Response = await http.get("/api/documents")
    assert version.file_id in {
        item.file_id for item in DOCUMENTS.validate_json(documents.content, strict=True)
    }
    history: httpx.Response = await http.get(f"/api/documents/{version.file_id}/versions")
    assert VERSIONS.validate_json(history.content, strict=True) == [version]
    metadata: httpx.Response = await http.get(f"/api/document-versions/{version.version_id}")
    assert DocumentVersionView.model_validate_json(metadata.content, strict=True) == version
    raw: httpx.Response = await http.get(f"/api/document-versions/{version.version_id}/content")
    assert raw.content == b"# BRD\nThe system shall retain data."
    assert raw.headers["etag"] == f'"{version.sha256}"'
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in raw.headers["content-disposition"]
    response: httpx.Response = await http.get(f"/api/document-versions/{version.version_id}/parsed")
    parsed: ParsedDocument = PARSED_DOCUMENT.validate_json(response.content, strict=True)
    assert parsed.version_id == version.version_id
    assert parsed.fragments[-1].text == "The system shall retain data."


async def test_explicit_new_revision_and_operation_are_idempotent(
    client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    http: httpx.AsyncClient = client[0]
    original: DocumentVersionView = await new_document(http)
    operation_id: UUID = uuid4()
    url: str = f"/api/documents/{original.file_id}/versions"
    params: dict[str, str] = {"operation_id": str(operation_id), "filename": "changed.txt"}
    response: httpx.Response = await http.post(
        url, params=params, content=b"Changed content", headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 201
    version: DocumentVersionView = DocumentVersionView.model_validate_json(
        response.content, strict=True
    )
    replay: httpx.Response = await http.post(
        url, params=params, content=b"Changed content", headers={"Content-Type": "text/plain"}
    )
    assert DocumentVersionView.model_validate_json(replay.content, strict=True) == version
    operation: httpx.Response = await http.get(f"/api/document-uploads/{operation_id}")
    assert (
        UploadOperationView.model_validate_json(operation.content, strict=True).version == version
    )
    assert (await http.post("/api/document-uploads/recover")).status_code == 200
    assert (
        await http.get(f"/api/document-versions/{original.version_id}/content")
    ).content == b"# BRD\nThe system shall retain data."
    conflict: httpx.Response = await http.post(
        url, params=params, content=b"Changed again", headers={"Content-Type": "text/plain"}
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    ("filename", "mime", "content", "status", "code"),
    [
        ("../private.txt", "text/plain", b"x", 422, "invalid_filename"),
        ("image.png", "image/png", b"x", 415, "unsupported_format"),
        ("brd.md", "image/png", b"x", 415, "invalid_mime"),
        ("brd.txt", "text/plain", b"\x00", 422, "invalid_text_encoding"),
        ("brd.txt", "text/plain", b"x" * 4097, 413, "document_too_large"),
        ("brd.txt", "text/plain", b"", 422, "empty_document"),
    ],
)
async def test_untrusted_upload_returns_typed_actionable_error(
    client: tuple[httpx.AsyncClient, AsyncEngine],
    filename: str,
    mime: str,
    content: bytes,
    status: int,
    code: str,
) -> None:
    response: httpx.Response = await client[0].post(
        "/api/documents",
        params={"operation_id": str(uuid4()), "filename": filename},
        headers={"Content-Type": mime},
        content=content,
    )
    assert response.status_code == status
    assert DocumentErrorView.model_validate_json(response.content, strict=True).code == code


async def test_unknown_documents_and_malformed_commands_are_safe(
    client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    http: httpx.AsyncClient = client[0]
    assert (await http.get(f"/api/document-versions/{uuid4()}")).status_code == 404
    assert (await http.get(f"/api/documents/{uuid4()}/versions")).status_code == 404
    assert (await http.get(f"/api/document-uploads/{uuid4()}")).status_code == 404
    assert (
        await http.post(
            "/api/documents",
            params={"operation_id": "invalid", "filename": "brd.txt"},
            content=b"x",
        )
    ).status_code == 422
    assert (
        await http.post(
            "/api/documents",
            params={"operation_id": str(uuid4()), "filename": "x" * 256},
            content=b"x",
        )
    ).status_code == 422


async def test_message_pin_keeps_exact_old_version(
    client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    http: httpx.AsyncClient = client[0]
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        client[1], expire_on_commit=False
    )
    stores: SqlAlchemyStoreFactory = SqlAlchemyStoreFactory(sessions)
    store: ChatStore
    async with stores.open() as store:
        chat: ChatView = await store.create_chat("Pinned source")
        await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Reference"), "fake", "test"
        )
        snapshot: ChatSnapshot = await store.queries.snapshot(chat.id)
    message_id: UUID = snapshot.messages[0].id
    version: DocumentVersionView = await new_document(http)
    attached: httpx.Response = await http.post(
        f"/api/messages/{message_id}/document-versions",
        json={"version_id": str(version.version_id)},
    )
    assert attached.status_code == 200
    repeated: httpx.Response = await http.post(
        f"/api/messages/{message_id}/document-versions",
        json={"version_id": str(version.version_id)},
    )
    assert repeated.status_code == 200
    pins: httpx.Response = await http.get(f"/api/messages/{message_id}/document-versions")
    assert VERSIONS.validate_json(pins.content, strict=True) == [version]
    assert (await http.get(f"/api/messages/{uuid4()}/document-versions")).status_code == 404
    assert (
        await http.post(
            f"/api/messages/{uuid4()}/document-versions",
            json={"version_id": str(version.version_id)},
        )
    ).status_code == 404

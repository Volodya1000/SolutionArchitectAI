from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import create_autospec
from uuid import UUID, uuid4

import pytest
from docx import Document
from docx.document import Document as DocxDocument

from solution_architect_ai.application.models.document_dto import DocumentVersionView, StoredParse
from solution_architect_ai.application.protocols.document_protocols import DocumentStore, StagedFile
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_identity import (
    PARSED_DOCUMENT,
    parse_digest,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.validation.markdown_structure import structural_fragment_ids
from solution_architect_ai.domain.documents import DocumentStructure, MarkdownTable, ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.parsers.document_validator import DOCX_MIME
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage


@dataclass(frozen=True)
class DocumentCase:
    document: ParsedDocument
    version: DocumentVersionView
    storage: LocalFileStorage


@dataclass
class ParseCounter:
    calls: int = 0


def source_content(document_format: str) -> tuple[str, str, bytes]:
    if document_format == "markdown":
        return "rules.md", "text/markdown", b"ID | Rule\n--- | ---\nR1 | Keep records"
    if document_format == "text":
        return "rules.txt", "text/plain", "Система принимает только A | B\n--- | ---".encode()
    if document_format == "pdf":
        source: Path = Path(__file__).parents[3] / "docs/pdf/example.pdf"
        return source.name, "application/pdf", source.read_bytes()
    document: DocxDocument = Document()
    document.add_paragraph("Keep records for 30 days.")
    output: BytesIO = BytesIO()
    document.save(output)
    return "rules.docx", DOCX_MIME, output.getvalue()


async def content_chunks(content: bytes) -> AsyncGenerator[bytes]:
    yield content


async def make_document_case(tmp_path: Path, document_format: str) -> DocumentCase:
    filename: str
    mime: str
    content: bytes
    filename, mime, content = source_content(document_format)
    document: ParsedDocument = DocumentParser().parse(uuid4(), uuid4(), content, filename, mime)
    task_id: UUID = uuid4()
    version: DocumentVersionView = DocumentVersionView(
        file_id=document.file_id,
        version_id=document.version_id,
        task_id=task_id,
        sha256=document.sha256,
        mime_type=mime,
        size=len(content),
        original_name=filename,
        uploaded_at=datetime.now(UTC),
        storage_key=f"{task_id}/{document.version_id}",
    )
    storage: LocalFileStorage = LocalFileStorage(tmp_path, max_bytes=1_000_000)
    staged: StagedFile = await storage.stage(content_chunks(content))
    await storage.publish(staged, version.storage_key)
    await storage.discard(staged)
    return DocumentCase(document, version, storage)


def forged_stored_parse(document: ParsedDocument) -> StoredParse:
    injected: ParsedDocument = replace(
        document, structure=DocumentStructure((MarkdownTable(1, 2, 3, "FORGED HEADER"),))
    )
    # Reproduce a persisted JSON field that can be altered without changing the
    # historical digest. The read must ignore it rather than trust its type.
    decoded: ParsedDocument = PARSED_DOCUMENT.validate_json(PARSED_DOCUMENT.dump_json(injected))
    assert parse_digest(decoded) == parse_digest(document)
    return StoredParse(document=decoded, digest=parse_digest(document))


def make_service(
    document_case: DocumentCase,
    saved: StoredParse | None,
    parser: DocumentParser,
    monkeypatch: pytest.MonkeyPatch,
) -> DocumentService:
    store: DocumentStore = create_autospec(DocumentStore, instance=True)

    async def version(_version_id: UUID) -> DocumentVersionView:
        return document_case.version

    async def get_parse(_version_id: UUID) -> StoredParse | None:
        return saved

    async def save_parse(parsed: StoredParse) -> StoredParse:
        nonlocal saved
        saved = StoredParse(document=replace(parsed.document, structure=None), digest=parsed.digest)
        return parsed

    @asynccontextmanager
    async def open_store() -> AsyncGenerator[DocumentStore]:
        yield store

    context: StoreContext[DocumentStore] = create_autospec(StoreContext, instance=True)
    monkeypatch.setattr(context, "open", open_store)
    monkeypatch.setattr(store, "get_version", version)
    monkeypatch.setattr(store, "get_parse", get_parse)
    monkeypatch.setattr(store, "save_parse", save_parse)
    return DocumentService(context, document_case.storage, parser)


def counted_parser(counter: ParseCounter, monkeypatch: pytest.MonkeyPatch) -> DocumentParser:
    parser: DocumentParser = DocumentParser()
    original_parse: Callable[[UUID, UUID, bytes, str, str], ParsedDocument] = parser.parse

    def parse(
        file_id: UUID,
        version_id: UUID,
        content: bytes,
        filename: str,
        mime_type: str,
    ) -> ParsedDocument:
        counter.calls += 1
        return original_parse(file_id, version_id, content, filename, mime_type)

    monkeypatch.setattr(parser, "parse", parse)
    return parser


@pytest.mark.anyio
@pytest.mark.parametrize("document_format", ["markdown", "text", "docx", "pdf"])
@pytest.mark.parametrize("cached", [False, True])
async def test_runtime_structure_comes_from_verified_bytes_and_authoritative_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document_format: str,
    cached: bool,
) -> None:
    document_case: DocumentCase = await make_document_case(tmp_path, document_format)
    saved: StoredParse | None = forged_stored_parse(document_case.document) if cached else None
    counter: ParseCounter = ParseCounter()
    service: DocumentService = make_service(
        document_case, saved, counted_parser(counter, monkeypatch), monkeypatch
    )
    loaded: ParsedDocument = await service.get_parsed_document(document_case.version.version_id)
    assert loaded.fragments == document_case.document.fragments
    assert loaded.sha256 == document_case.document.sha256
    assert parse_digest(loaded) == parse_digest(document_case.document)
    assert loaded.structure == (
        document_case.document.structure if document_format == "markdown" else None
    )
    assert counter.calls == (1 if document_format == "markdown" or not cached else 0)
    if document_format == "text":
        assert not structural_fragment_ids(loaded)
        assert loaded.fragments[0].text == "Система принимает только A | B"
    if saved is not None:
        assert saved.document.structure is not None
        assert saved.document.structure.tables[0].header_text == "FORGED HEADER"


@pytest.mark.anyio
async def test_legacy_markdown_structure_is_rederived_without_rewriting_saved_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_case: DocumentCase = await make_document_case(tmp_path, "markdown")
    legacy: ParsedDocument = PARSED_DOCUMENT.validate_json(
        PARSED_DOCUMENT.dump_json(document_case.document, exclude={"structure"})
    )
    saved: StoredParse = StoredParse(document=legacy, digest=parse_digest(legacy))
    counter: ParseCounter = ParseCounter()
    service: DocumentService = make_service(
        document_case, saved, counted_parser(counter, monkeypatch), monkeypatch
    )
    first: ParsedDocument = await service.get_parsed_document(legacy.version_id)
    second: ParsedDocument = await service.get_parsed_document(legacy.version_id)
    assert first == second
    assert first.fragments == legacy.fragments
    assert first.structure == document_case.document.structure
    assert parse_digest(first) == saved.digest
    assert saved.document.structure is None
    assert counter.calls == 2

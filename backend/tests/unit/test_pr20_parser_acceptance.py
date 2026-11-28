import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Final, cast
from unittest.mock import create_autospec
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.table import Table

from solution_architect_ai.application.agents.extraction_result_mapper import verify_result
from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.context_models import (
    ContextFragment,
    ContextPack,
    ContextPart,
    ContextPolicy,
)
from solution_architect_ai.application.context.discussion_sources import (
    DiscussionSourceContextBuilder,
)
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView, StoredParse
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedRequirement,
    PartResult,
    RequirementsExtraction,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import ModelProfile, StructuredMode
from solution_architect_ai.application.protocols.document_protocols import (
    DocumentStore,
    FileStorage,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.services.document_identity import (
    PARSED_DOCUMENT,
    parse_digest,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.validation.markdown_structure import structural_fragment_ids
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument, SourceLocator
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.parsers.document_validator import DOCX_MIME

PIPE_STATEMENT: Final[str] = "Система принимает только A | B"


def context(document: ParsedDocument, output_limit: int = 6912) -> ContextPack:
    return ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, output_limit, 256)
    ).build((document,), "")


@pytest.mark.parametrize(
    ("filename", "mime_type", "text"),
    [
        ("rules.txt", "text/plain", f"{PIPE_STATEMENT}\n--- | ---"),
        ("rules.md", "text/markdown", f"```text\n{PIPE_STATEMENT}\n--- | ---\n```"),
    ],
)
def test_literal_pipe_statement_keeps_its_exact_candidate_quote(
    filename: str, mime_type: str, text: str
) -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), text.encode(), filename, mime_type
    )
    pack: ContextPack = context(document)
    statement: DocumentFragment = next(
        fragment for fragment in document.fragments if fragment.text == PIPE_STATEMENT
    )
    result: PartResult = verify_result(
        RequirementsExtraction(
            requirements=[
                ExtractedRequirement(
                    category="functional",
                    original_text=PIPE_STATEMENT,
                    normalized_text=PIPE_STATEMENT,
                    evidence=[
                        Evidence(fragment_id=str(statement.fragment_id), quote=PIPE_STATEMENT)
                    ],
                )
            ],
            gaps=[],
            contradictions=[],
        ),
        pack.parts[0],
    )
    assert len(result.requirements) == 1
    assert result.requirements[0].sources[0].quote == PIPE_STATEMENT
    assert not structural_fragment_ids(document)


def test_reporting_separator_is_not_sent_to_semantic_extraction() -> None:
    source: Path = Path(__file__).parents[3] / "docs/examples/pr3/reporting-system-incomplete.md"
    content: bytes = source.read_bytes()
    version_id: UUID = uuid4()
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), version_id, content, source.name, "text/markdown"
    )
    pack: ContextPack = context(document)
    header: DocumentFragment = next(item for item in document.fragments if item.locator.start == 48)
    separator: DocumentFragment = next(
        item for item in document.fragments if item.locator.start == 49
    )
    kafka: DocumentFragment = next(item for item in document.fragments if item.locator.start == 50)
    assert "Kafka" in kafka.text
    assert all(separator.text not in part.messages[-1].content for part in pack.parts)
    assert str(header.fragment_id) in structural_fragment_ids(document)
    assert document.sha256 == sha256(content).hexdigest()
    assert document.text == content.decode()
    item: DocumentFragment
    for item in document.fragments:
        assert item.text == content.decode().splitlines()[item.locator.start - 1]
        assert item.fragment_id == uuid5(
            version_id,
            f"documents-v1/lines/{item.locator.start}/{item.locator.end}/{item.locator.path}",
        )


def test_table_row_keeps_escaped_pipe_and_empty_header_context_across_windows() -> None:
    header: str = "| ID | Retention \\| policy | |"
    rows: str = "\n".join(f"| R-{index} | Keep records 30 days | Reject |" for index in range(15))
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), f"{header}\n|---|---|---|\n{rows}".encode(), "rules.md", "text/markdown"
    )
    pack: ContextPack = context(document, 1200)
    assert len(pack.parts) > 1
    part: ContextPart
    for part in pack.parts:
        fragment: ContextFragment
        for fragment in part.fragments:
            if fragment.text.startswith("| R-"):
                assert fragment.table_header == header
                payload: dict[str, list[dict[str, str]]] = json.loads(part.messages[-1].content)
                assert any(header in item["section"] for item in payload["fragments"])
                assert fragment.locator.section == ""


def omitted_docx_content() -> bytes:
    document: DocxDocument = Document()
    table: Table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "ID"
    table.cell(0, 1).text = "Срок хранения"
    table.cell(0, 2).text = "Поведение"
    table.cell(1, 1).text = "30 дней"
    table.cell(1, 2).text = "Отказать"
    output: BytesIO = BytesIO()
    document.save(output)
    return omit_first_docx_cell(output.getvalue())


def omit_first_docx_cell(content: bytes) -> bytes:
    namespace: str = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    output: BytesIO = BytesIO()
    original: ZipFile
    modified: ZipFile
    with ZipFile(BytesIO(content)) as original, ZipFile(output, "w") as modified:
        name: str
        for name in original.namelist():
            body: bytes = original.read(name)
            if name == "word/document.xml":
                root: BaseOxmlElement = parse_xml(body)
                row: BaseOxmlElement = root.findall(f".//{namespace}tr")[1]
                row.remove(row.findall(f"{namespace}tc")[0])
                properties: BaseOxmlElement = cast(BaseOxmlElement, OxmlElement("w:trPr"))
                grid_before: BaseOxmlElement = cast(BaseOxmlElement, OxmlElement("w:gridBefore"))
                grid_before.set(f"{namespace}val", "1")
                properties.append(grid_before)
                row.insert(0, properties)
                body = root.xml.encode()
            modified.writestr(name, body)
    return output.getvalue()


def test_docx_omitted_first_grid_cell_preserves_column_headings() -> None:
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), omitted_docx_content(), "rules.docx", DOCX_MIME
    )
    retention: DocumentFragment = next(item for item in parsed.fragments if item.text == "30 дней")
    behavior: DocumentFragment = next(item for item in parsed.fragments if item.text == "Отказать")
    assert "column 2: Срок хранения" in retention.locator.section
    assert "/row/2/cell/2/" in retention.locator.path
    assert "column 3: Поведение" in behavior.locator.section
    assert "/row/2/cell/3/" in behavior.locator.path


def test_legacy_parse_digest_is_identical_without_new_structure_metadata() -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), b"ID | Rule\n--- | ---\nR1 | Keep data", "rules.md", "text/markdown"
    )
    legacy_body: dict[str, object] = json.loads(PARSED_DOCUMENT.dump_json(document))
    legacy_body.pop("structure", None)
    legacy_bytes: bytes = json.dumps(
        legacy_body, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert parse_digest(document) == sha256(legacy_bytes).hexdigest()
    restored: ParsedDocument = PARSED_DOCUMENT.validate_json(legacy_bytes)
    assert restored.fragments == document.fragments
    assert parse_digest(restored) == sha256(legacy_bytes).hexdigest()


def test_clarification_omits_separator_and_keeps_table_header_context() -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        b"ID | Retention\n--- | ---\nR1 | Keep 30 days",
        "rules.md",
        "text/markdown",
    )
    clarification: ClarificationContext = ClarificationContextBuilder().build(
        (document,), [], [], [], ModelProfile("test", StructuredMode.JSON_TEXT, 12288, 6912)
    )
    assert "--- | ---" not in clarification.part.messages[-1].content
    assert clarification.payload.fragments[-1].table_header == "ID | Retention"
    assert clarification.part.fragments[-1].locator == document.fragments[-1].locator


@pytest.mark.anyio
@pytest.mark.parametrize("row_count", [1, 10])
async def test_discussion_neighbors_omit_separator_and_preserve_exact_source(
    monkeypatch: pytest.MonkeyPatch,
    row_count: int,
) -> None:
    rows: str = "\n".join(f"R{index} | Keep 30 days" for index in range(1, row_count + 1))
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        f"ID | Retention\n--- | ---\n{rows}".encode(),
        "rules.md",
        "text/markdown",
    )
    service: DiscussionService = create_autospec(DiscussionService, instance=True)
    service.documents_service = create_autospec(DocumentService, instance=True)

    async def get_document(_version_id: UUID) -> ParsedDocument:
        return document

    async def reference(_version_id: UUID, fragment_id: UUID) -> SourceRef:
        source: DocumentFragment = next(
            item for item in document.fragments if item.fragment_id == fragment_id
        )
        return verify_evidence(
            Evidence(fragment_id=str(fragment_id), quote=source.text), context(document).parts[0]
        )

    monkeypatch.setattr(service.documents_service, "get_parsed_document", get_document)
    monkeypatch.setattr(service, "source_reference", reference)
    selected: SourceRef = await reference(document.version_id, document.fragments[-1].fragment_id)
    sources: list[SourceRef]
    count: int
    sources, count = await DiscussionSourceContextBuilder(service).related_sources(
        selected, {selected.fragment_id}, 16000
    )
    assert count == row_count + 2
    assert "ID | Retention" in [source.quote for source in sources]
    assert all(source.quote != "--- | ---" for source in sources)
    assert selected.quote == f"R{row_count} | Keep 30 days"
    assert selected.locator is not None
    assert selected.locator.start == row_count + 2


def legacy_docx_parse(parsed: ParsedDocument) -> ParsedDocument:
    retention: DocumentFragment = next(item for item in parsed.fragments if item.text == "30 дней")
    old_locator: SourceLocator = replace(
        retention.locator,
        path=retention.locator.path.replace("/cell/2/", "/cell/1/"),
        section=" | row 2: 30 дней | column 1: ID",
    )
    old_fragment: DocumentFragment = replace(
        retention,
        locator=old_locator,
        fragment_id=uuid5(parsed.version_id, f"documents-v1/table_cell/1/1/{old_locator.path}"),
    )
    return replace(
        parsed,
        fragments=tuple(
            old_fragment if item.fragment_id == retention.fragment_id else item
            for item in parsed.fragments
        ),
    )


def saved_document_service(monkeypatch: pytest.MonkeyPatch, saved: StoredParse) -> DocumentService:
    document_store: DocumentStore = create_autospec(DocumentStore, instance=True)

    async def get_parse(_version_id: UUID) -> StoredParse:
        return saved

    @asynccontextmanager
    async def open_store() -> AsyncIterator[DocumentStore]:
        yield document_store

    store_context: StoreContext[DocumentStore] = create_autospec(StoreContext, instance=True)
    monkeypatch.setattr(store_context, "open", open_store)
    monkeypatch.setattr(document_store, "get_parse", get_parse)
    return DocumentService(
        store_context, create_autospec(FileStorage, instance=True), DocumentParser()
    )


@pytest.mark.anyio
@pytest.mark.parametrize("document_format", ["markdown", "docx"])
async def test_legacy_saved_parse_keeps_sources_while_deriving_table_syntax(
    monkeypatch: pytest.MonkeyPatch,
    document_format: str,
) -> None:
    content: bytes = (
        b"ID | Rule\n--- | ---\nR1 | Keep data"
        if document_format == "markdown"
        else omitted_docx_content()
    )
    filename: str = "rules.md" if document_format == "markdown" else "rules.docx"
    mime: str = "text/markdown" if document_format == "markdown" else DOCX_MIME
    parsed: ParsedDocument = DocumentParser().parse(uuid4(), uuid4(), content, filename, mime)
    if document_format == "docx":
        parsed = legacy_docx_parse(parsed)
    legacy_bytes: bytes = PARSED_DOCUMENT.dump_json(parsed, exclude={"structure"})
    legacy: ParsedDocument = PARSED_DOCUMENT.validate_json(legacy_bytes)
    saved: StoredParse = StoredParse(document=legacy, digest=sha256(legacy_bytes).hexdigest())
    service: DocumentService = saved_document_service(monkeypatch, saved)
    version: DocumentVersionView = DocumentVersionView(
        file_id=parsed.file_id,
        version_id=parsed.version_id,
        task_id=uuid4(),
        sha256=parsed.sha256,
        mime_type=mime,
        size=len(content),
        original_name=filename,
        uploaded_at=datetime.now(UTC),
        storage_key="legacy-version",
    )

    async def load(_version_id: UUID) -> tuple[DocumentVersionView, bytes]:
        return version, content

    monkeypatch.setattr(service, "_load_version_content", load)
    loaded: ParsedDocument = await service.get_parsed_document(parsed.version_id)
    assert loaded.structure == parsed.structure
    assert loaded.fragments == legacy.fragments
    assert loaded.sha256 == legacy.sha256
    assert parse_digest(loaded) == saved.digest
    assert saved.document.structure is None
    if document_format == "markdown":
        assert str(legacy.fragments[1].fragment_id) in structural_fragment_ids(loaded)
    else:
        old_retention: DocumentFragment = next(
            item for item in loaded.fragments if item.text == "30 дней"
        )
        assert "column 1: ID" in old_retention.locator.section
        assert "/cell/1/" in old_retention.locator.path


def test_docx_merged_cell_appears_once_per_row_with_grid_column_context() -> None:
    document: DocxDocument = Document()
    table: Table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "ID"
    table.cell(0, 1).text = "Retention"
    table.cell(0, 2).text = "Behavior"
    table.cell(1, 0).text = "R1"
    table.cell(1, 1).merge(table.cell(1, 2)).text = "Keep 30 days and reject older dates"
    output: BytesIO = BytesIO()
    document.save(output)
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), output.getvalue(), "rules.docx", DOCX_MIME
    )
    matches: list[DocumentFragment] = [item for item in parsed.fragments if "Keep 30" in item.text]
    assert len(matches) == 1
    assert "column 2: Retention" in matches[0].locator.section
    assert "/row/2/cell/2/" in matches[0].locator.path

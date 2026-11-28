from collections.abc import Iterator
from hashlib import sha256
from io import BytesIO
from typing import Final
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.section import Section, _Footer, _Header
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.infrastructure.parsers.document_fragments import (
    PARSER_VERSION,
    collect_fragments,
    fragment,
)

_UNSUPPORTED_TAGS: Final[tuple[str, ...]] = (
    "w:ins",
    "w:del",
    "w:txbxContent",
    "w:drawing",
    "w:object",
    "w:altChunk",
    "w:sdt",
    "w:customXml",
    "w:smartTag",
    "w:subDoc",
    "w:moveFrom",
    "w:moveTo",
    "w:fldSimple",
    "w:instrText",
    "w:sym",
    "w:pict",
)


def validate_archive(content: bytes) -> None:
    try:
        archive: ZipFile
        with ZipFile(BytesIO(content)) as archive:
            validate_zip(archive)
    except BadZipFile:
        raise DocumentFailure(DocumentErrorCode.INVALID_MIME) from None


def validate_zip(archive: ZipFile) -> None:
    entries: list[ZipInfo] = archive.infolist()
    size: int = sum(entry.file_size for entry in entries)
    if size > 50 * 1024 * 1024 or len(entries) > 2000:
        raise DocumentFailure(DocumentErrorCode.TOO_LARGE)
    if "word/document.xml" not in archive.namelist():
        raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
    entry: ZipInfo
    for entry in entries:
        validate_entry(entry)


def validate_entry(entry: ZipInfo) -> None:
    if entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)
    if entry.flag_bits & 1:
        raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)
    if entry.file_size > max(entry.compress_size, 1) * 500:
        raise DocumentFailure(DocumentErrorCode.TOO_LARGE)
    unsupported: tuple[str, ...] = (
        "word/embeddings/",
        "word/vbaProject",
        "word/comments",
        "word/footnotes",
        "word/endnotes",
    )
    if entry.filename.startswith(unsupported):
        raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)


def parse_docx(file_id: UUID, version_id: UUID, content: bytes) -> ParsedDocument:
    try:
        validate_archive(content)
        document: DocxDocument = Document(BytesIO(content))
        reject_unsupported(document)
        fragments: tuple[DocumentFragment, ...] = collect_fragments(
            walk_blocks(document.iter_inner_content(), version_id, "body", "")
        )
    except (BadZipFile, KeyError, ValueError, SyntaxError):
        raise DocumentFailure(DocumentErrorCode.PARSE_FAILED) from None
    if not fragments:
        raise DocumentFailure(DocumentErrorCode.EMPTY)
    return ParsedDocument(
        file_id,
        version_id,
        sha256(content).hexdigest(),
        PARSER_VERSION,
        "\n".join(item.text for item in fragments),
        fragments,
    )


def reject_unsupported(document: DocxDocument) -> None:
    tag: str
    for tag in _UNSUPPORTED_TAGS:
        if next(document.element.iter(qn(tag)), None) is not None:
            raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)
    if any(header_has_content(header) for header in headers(document)):
        raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)


def header_has_content(header: _Header | _Footer) -> bool:
    if any(next(header.part.element.iter(qn(tag)), None) is not None for tag in _UNSUPPORTED_TAGS):
        return True
    return any(
        isinstance(block, Table) or block.text.strip() for block in header.iter_inner_content()
    )


def headers(document: DocxDocument) -> Iterator[_Header | _Footer]:
    section: Section
    for section in document.sections:
        yield from (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        )


def walk_blocks(
    blocks: Iterator[Paragraph | Table], version_id: UUID, path: str, section: str
) -> Iterator[DocumentFragment]:
    index: int
    block: Paragraph | Table
    for index, block in enumerate(blocks, 1):
        location: str = f"{path}/block/{index}"
        if isinstance(block, Table):
            yield from walk_table(block, version_id, location, section)
            continue
        if block.style is not None and block.style.name.startswith("Heading"):
            section = block.text
        item: DocumentFragment | None = paragraph_fragment(
            block, version_id, location, section, index
        )
        if item is not None:
            yield item


def paragraph_fragment(
    block: Paragraph, version_id: UUID, path: str, section: str, index: int
) -> DocumentFragment | None:
    if not block.text.strip():
        return None
    kind: LocatorKind = LocatorKind.TABLE_CELL if "/cell/" in path else LocatorKind.PARAGRAPH
    return fragment(version_id, block.text, SourceLocator(kind, index, index, section, path))


def walk_table(
    table: Table, version_id: UUID, path: str, section: str
) -> Iterator[DocumentFragment]:
    row_index: int
    row: _Row
    for row_index, row in enumerate(table.rows, 1):
        seen: set[int] = set()
        cell_index: int
        cell: _Cell
        for cell_index, cell in enumerate(row.cells, row.grid_cols_before + 1):
            if id(cell) not in seen:
                seen.add(id(cell))
                cell_path: str = f"{path}/row/{row_index}/cell/{cell_index}"
                context: str = cell_context(table, row, row_index, cell_index, section)
                yield from walk_blocks(cell.iter_inner_content(), version_id, cell_path, context)


def cell_context(table: Table, row: _Row, row_index: int, cell_index: int, section: str) -> str:
    headings: tuple[_Cell, ...] = table.rows[0].cells
    heading_index: int = cell_index - table.rows[0].grid_cols_before - 1
    heading: str = headings[heading_index].text[:256] if 0 <= heading_index < len(headings) else ""
    key: str = row.cells[0].text[:256] if row.cells and row.grid_cols_before == 0 else ""
    return f"{section} | row {row_index}: {key} | column {cell_index}: {heading}"

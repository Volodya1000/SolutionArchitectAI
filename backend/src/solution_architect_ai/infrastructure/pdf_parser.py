from hashlib import sha256
from io import BytesIO
from uuid import UUID

from pypdf import PageObject, PdfReader
from pypdf.errors import PdfReadError

from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.infrastructure.document_fragments import (
    PARSER_VERSION,
    check_parse_size,
    fragment,
)


def parse_pdf(file_id: UUID, version_id: UUID, content: bytes) -> ParsedDocument:
    try:
        reader: PdfReader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 500:
            raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_CONTENT)
        return extract_pdf(reader, file_id, version_id, content)
    except (PdfReadError, ValueError, KeyError, TypeError):
        raise DocumentFailure(DocumentErrorCode.PARSE_FAILED) from None


def extract_pdf(
    reader: PdfReader, file_id: UUID, version_id: UUID, content: bytes
) -> ParsedDocument:
    fragments: list[DocumentFragment] = []
    pages: list[str] = []
    empty: list[str] = []
    size: int = 0
    page_index: int
    page: PageObject
    for page_index, page in enumerate(reader.pages):
        page_text: str = page.extract_text(
            extraction_mode="layout", layout_mode_strip_rotated=False
        )
        pages.append(page_text)
        size += len(page_text)
        check_parse_size(size, len(fragments))
        if not page_text.strip():
            empty.append(str(page_index + 1))
        fragments.extend(page_fragments(version_id, page_index + 1, page_text))
        check_parse_size(size, len(fragments))
    if not fragments:
        raise DocumentFailure(DocumentErrorCode.NO_TEXT)
    warnings: list[str] = ["pdf_layout_and_tables_require_manual_review"]
    if empty:
        warnings.append("pdf_pages_without_text:" + ",".join(empty))
    return ParsedDocument(
        file_id,
        version_id,
        sha256(content).hexdigest(),
        PARSER_VERSION,
        "\n\f\n".join(pages),
        tuple(fragments),
        tuple(warnings),
    )


def page_fragments(version_id: UUID, page_number: int, text: str) -> list[DocumentFragment]:
    fragments: list[DocumentFragment] = []
    line_index: int
    line: str
    for line_index, line in enumerate(text.splitlines(), 1):
        if line.strip():
            check_parse_size(len(text), len(fragments) + 1)
            locator: SourceLocator = SourceLocator(
                LocatorKind.PAGE,
                page_number,
                page_number,
                "",
                f"page/{page_number}/line/{line_index}",
            )
            fragments.append(fragment(version_id, line, locator))
    return fragments

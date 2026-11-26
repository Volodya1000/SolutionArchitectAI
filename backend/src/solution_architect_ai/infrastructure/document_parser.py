import re
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from markdown_it import MarkdownIt
from markdown_it.token import Token

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
from solution_architect_ai.infrastructure.docx_parser import parse_docx, validate_archive
from solution_architect_ai.infrastructure.pdf_parser import parse_pdf

PDF_MIME: Final[str] = "application/pdf"
DOCX_MIME: Final[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_FORMATS: Final[dict[str, str]] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": PDF_MIME,
    ".docx": DOCX_MIME,
}


def text_content(content: bytes) -> str:
    try:
        text: str = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentFailure(DocumentErrorCode.INVALID_TEXT) from None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise DocumentFailure(DocumentErrorCode.INVALID_TEXT)
    if not text.strip():
        raise DocumentFailure(DocumentErrorCode.EMPTY)
    check_parse_size(len(text), sum(1 for line in text.splitlines() if line.strip()))
    return text


class DocumentParser:
    def validate(self, content: bytes, filename: str, mime_type: str) -> str:
        if filename in {".", ".."} or re.search(r'[\\/:\x00-\x1f<>"|?*]', filename):
            raise DocumentFailure(DocumentErrorCode.INVALID_FILENAME)
        expected: str | None = _FORMATS.get(PurePosixPath(filename).suffix.lower())
        if expected is None:
            raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_FORMAT)
        supplied: str = mime_type.partition(";")[0].strip().lower()
        if supplied != expected:
            raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
        self.validate_signature(content, expected)
        return expected

    def validate_signature(self, content: bytes, mime_type: str) -> None:
        if not content:
            raise DocumentFailure(DocumentErrorCode.EMPTY)
        signatures: dict[str, bytes] = {PDF_MIME: b"%PDF-", DOCX_MIME: b"PK\x03\x04"}
        signature: bytes | None = signatures.get(mime_type)
        if signature is not None:
            if not content.startswith(signature):
                raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
            if mime_type == DOCX_MIME:
                validate_archive(content)
            return
        if content.startswith((b"%PDF-", b"PK\x03\x04", b"MZ", b"\x89PNG")):
            raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
        text_content(content)

    def parse(
        self, file_id: UUID, version_id: UUID, content: bytes, filename: str, mime_type: str
    ) -> ParsedDocument:
        mime: str = self.validate(content, filename, mime_type)
        if mime == PDF_MIME:
            return parse_pdf(file_id, version_id, content)
        if mime == DOCX_MIME:
            return parse_docx(file_id, version_id, content)
        text: str = text_content(content)
        sections: dict[int, str] = self.headings(text) if mime == "text/markdown" else {}
        section: str = ""
        fragments: list[DocumentFragment] = []
        index: int
        line: str
        for index, line in enumerate(text.splitlines(), 1):
            section = sections.get(index, section)
            if line.strip():
                fragments.append(
                    fragment(
                        version_id, line, SourceLocator(LocatorKind.LINES, index, index, section)
                    )
                )
        return ParsedDocument(
            file_id, version_id, sha256(content).hexdigest(), PARSER_VERSION, text, tuple(fragments)
        )

    def headings(self, text: str) -> dict[int, str]:
        tokens: list[Token] = MarkdownIt().parse(text)
        headings: dict[int, str] = {}
        index: int
        token: Token
        for index, token in enumerate(tokens):
            if token.type == "heading_open" and token.map is not None:
                headings[token.map[0] + 1] = tokens[index + 1].content
        return headings

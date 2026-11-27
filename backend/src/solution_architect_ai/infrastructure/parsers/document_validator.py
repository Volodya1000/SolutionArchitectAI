import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.infrastructure.parsers.document_fragments import check_parse_size
from solution_architect_ai.infrastructure.parsers.docx_parser import validate_archive

PDF_MIME: Final[str] = "application/pdf"
MARKDOWN_MIME: Final[str] = "text/markdown"
DOCX_MIME: Final[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_FORMATS: Final[dict[str, str]] = {
    ".txt": "text/plain",
    ".md": MARKDOWN_MIME,
    ".markdown": MARKDOWN_MIME,
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


@dataclass(frozen=True)
class ValidatedDocument:
    mime_type: str
    text: str | None


class DocumentValidator:
    def validate(self, content: bytes, filename: str, mime_type: str) -> ValidatedDocument:
        if filename in {".", ".."} or re.search(r'[\\/:\x00-\x1f<>"|?*]', filename):
            raise DocumentFailure(DocumentErrorCode.INVALID_FILENAME)
        expected: str | None = _FORMATS.get(PurePosixPath(filename).suffix.lower())
        if expected is None:
            raise DocumentFailure(DocumentErrorCode.UNSUPPORTED_FORMAT)
        supplied: str = mime_type.partition(";")[0].strip().lower()
        if supplied != expected:
            raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
        return ValidatedDocument(expected, self.validate_signature(content, expected))

    def validate_signature(self, content: bytes, mime_type: str) -> str | None:
        if not content:
            raise DocumentFailure(DocumentErrorCode.EMPTY)
        signatures: dict[str, bytes] = {PDF_MIME: b"%PDF-", DOCX_MIME: b"PK\x03\x04"}
        signature: bytes | None = signatures.get(mime_type)
        if signature is not None:
            if not content.startswith(signature):
                raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
            if mime_type == DOCX_MIME:
                validate_archive(content)
            return None
        self.validate_text_signature(content)
        return text_content(content)

    @staticmethod
    def validate_text_signature(content: bytes) -> None:
        if content.startswith(
            (
                b"%PDF-",
                b"PK\x03\x04",
                b"MZ",
                b"\x89PNG",
                b"GIF87a",
                b"GIF89a",
                b"\xff\xd8\xff",
                b"\x7fELF",
                b"SQLite format 3\x00",
            )
        ):
            raise DocumentFailure(DocumentErrorCode.INVALID_MIME)
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            raise DocumentFailure(DocumentErrorCode.INVALID_MIME)

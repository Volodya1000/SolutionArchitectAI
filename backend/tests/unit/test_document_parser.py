from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from markdown_it import MarkdownIt
from markdown_it.token import Token

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser


def parse(content: bytes, filename: str, mime: str) -> ParsedDocument:
    file_id: UUID = UUID("20000000-0000-4000-8000-000000000001")
    version_id: UUID = UUID("20000000-0000-4000-8000-000000000002")
    return DocumentParser().parse(file_id, version_id, content, filename, mime)


def test_markdown_preserves_lines_tables_sections_and_ids() -> None:
    content: bytes = b"# BRD\n\n## Data\n| Field | Rule |\n| --- | --- |\n| Total | Required |\n"
    first: ParsedDocument = parse(content, "brd.md", "text/markdown")
    second: ParsedDocument = parse(content, "brd.md", "text/markdown")
    assert first == second
    assert first.sha256 == sha256(content).hexdigest()
    assert any("Total" in fragment.text for fragment in first.fragments)
    assert any(fragment.locator.section == "Data" for fragment in first.fragments)
    for fragment in first.fragments:
        assert fragment.text == "\n".join(
            content.decode().splitlines()[fragment.locator.start - 1 : fragment.locator.end]
        )


@pytest.mark.parametrize(
    ("content", "filename", "mime"),
    [
        (b"%PDF-hidden", "a.txt", "text/plain"),
        (b"hello", "a.md", "image/png"),
        (b"\x00binary", "a.txt", "text/plain"),
        (b"\xff", "a.txt", "text/plain"),
        (b"", "a.txt", "text/plain"),
        (b"hello", "../a.txt", "text/plain"),
    ],
)
def test_invalid_content_is_rejected(content: bytes, filename: str, mime: str) -> None:
    with pytest.raises(DocumentFailure):
        parse(content, filename, mime)


def test_fragment_ids_are_bound_to_a_version() -> None:
    content: bytes = b"The service shall retain records."
    first: ParsedDocument = parse(content, "brd.txt", "text/plain")
    second: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), content, "brd.txt", "text/plain"
    )
    assert first.fragments[0].fragment_id != second.fragments[0].fragment_id


@pytest.mark.parametrize(
    "signature", [b"GIF89a", b"\xff\xd8\xff", b"\x7fELF", b"SQLite format 3\x00", b"RIFFxxxxWEBP"]
)
def test_known_binary_formats_have_a_mime_error(signature: bytes) -> None:
    with pytest.raises(DocumentFailure) as error:
        parse(signature, "BRD.txt", "text/plain")
    assert error.value.code == DocumentErrorCode.INVALID_MIME


def test_incomplete_markdown_heading_tokens_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def malformed(_parser: MarkdownIt, _text: str) -> list[Token]:
        heading: Token = Token("heading_open", "h1", 1)
        heading.map = [0, 1]
        return [heading]

    monkeypatch.setattr(MarkdownIt, "parse", malformed)
    assert not DocumentParser().headings("# BRD")

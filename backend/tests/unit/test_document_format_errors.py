from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import OxmlElement, parse_xml
from pypdf import PdfReader, PdfWriter

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.parsers.document_validator import DOCX_MIME


def test_utf8_bom_and_windows_newlines_are_reproducible() -> None:
    content: bytes = b"\xef\xbb\xbfTitle\r\nRequirement\r\n"
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), content, "input.TXT", "text/plain; charset=utf-8"
    )
    assert parsed.text == "Title\r\nRequirement\r\n"
    assert parsed.fragments[1].text == "Requirement"
    assert parsed.fragments[1].locator.start == 2


@pytest.mark.parametrize(
    ("content", "name", "mime", "code"),
    [
        (b"text", "brd.rtf", "text/plain", DocumentErrorCode.UNSUPPORTED_FORMAT),
        (b"not a pdf", "brd.pdf", "application/pdf", DocumentErrorCode.INVALID_MIME),
        (b"%PDF-1.7\ninvalid", "brd.pdf", "application/pdf", DocumentErrorCode.PARSE_FAILED),
        (b"not a ZIP", "brd.docx", DOCX_MIME, DocumentErrorCode.INVALID_MIME),
        (b"PK\x03\x04invalid", "brd.docx", DOCX_MIME, DocumentErrorCode.INVALID_MIME),
    ],
)
def test_claimed_binary_formats_are_validated(
    content: bytes, name: str, mime: str, code: DocumentErrorCode
) -> None:
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), content, name, mime)
    assert error.value.code == code


def zip_content(name: str, text: bytes) -> bytes:
    output: BytesIO = BytesIO()
    archive: ZipFile
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return output.getvalue()


def test_fake_docx_and_zip_expansion_attack_are_rejected() -> None:
    with pytest.raises(DocumentFailure) as impostor:
        DocumentParser().validate(zip_content("private.txt", b"hello"), "file.docx", DOCX_MIME)
    assert impostor.value.code == DocumentErrorCode.INVALID_MIME
    with pytest.raises(DocumentFailure) as bomb:
        DocumentParser().validate(
            zip_content("word/document.xml", b"x" * 1_000_000), "file.docx", DOCX_MIME
        )
    assert bomb.value.code == DocumentErrorCode.TOO_LARGE


def test_tracked_change_is_not_silently_ignored() -> None:
    document: DocxDocument = Document()
    document.add_paragraph("Visible requirement")
    document.element.body.append(OxmlElement("w:ins"))
    output: BytesIO = BytesIO()
    document.save(output)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), output.getvalue(), "file.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


def test_empty_docx_has_a_diagnostic() -> None:
    document: DocxDocument = Document()
    output: BytesIO = BytesIO()
    document.save(output)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), output.getvalue(), "empty.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.EMPTY


def test_mixed_pdf_exposes_pages_without_text() -> None:
    source: Path = Path(__file__).parents[3] / "docs" / "pdf" / "example.pdf"
    reader: PdfReader = PdfReader(source)
    writer: PdfWriter = PdfWriter()
    writer.add_page(reader.pages[1])
    writer.add_blank_page(width=100, height=100)
    output: BytesIO = BytesIO()
    writer.write(output)
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), output.getvalue(), "partial.pdf", "application/pdf"
    )
    assert "pdf_pages_without_text:2" in parsed.warnings
    assert any("R-01" in item.text for item in parsed.fragments)


def test_encrypted_pdf_returns_a_typed_failure() -> None:
    writer: PdfWriter = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("local-test-only")
    output: BytesIO = BytesIO()
    writer.write(output)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(
            uuid4(), uuid4(), output.getvalue(), "encrypted.pdf", "application/pdf"
        )
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


def test_content_control_text_is_not_silently_omitted() -> None:
    document: DocxDocument = Document()
    document.add_paragraph("Visible requirement")
    document.element.body.append(
        parse_xml(
            '<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:sdtContent><w:p><w:r><w:t>Hidden requirement</w:t></w:r></w:p></w:sdtContent></w:sdt>'
        )
    )
    output: BytesIO = BytesIO()
    document.save(output)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), output.getvalue(), "file.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


def test_fragment_explosion_is_rejected_before_unbounded_parse() -> None:
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(
            uuid4(), uuid4(), b"Requirement\n" * 20_001, "large.txt", "text/plain"
        )
    assert error.value.code == DocumentErrorCode.TOO_LARGE

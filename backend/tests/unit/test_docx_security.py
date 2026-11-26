from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import parse_xml
from docx.section import _Footer, _Header

from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.infrastructure.document_parser import DOCX_MIME, DocumentParser


def saved_document(document: DocxDocument) -> bytes:
    stream: BytesIO = BytesIO()
    document.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize("header_index", range(6))
@pytest.mark.parametrize("shape_tag", ["pict", "drawing"])
def test_text_in_header_or_footer_shapes_is_rejected(header_index: int, shape_tag: str) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("The system shall produce reports.")
    parts: tuple[_Header | _Footer, ...] = (
        document.sections[0].header,
        document.sections[0].footer,
        document.sections[0].first_page_header,
        document.sections[0].first_page_footer,
        document.sections[0].even_page_header,
        document.sections[0].even_page_footer,
    )
    parts[header_index].part.element.append(
        parse_xml(
            '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:r><w:{shape_tag}><w:txbxContent><w:p><w:r>"
            "<w:t>The system must encrypt all reports.</w:t>"
            f"</w:r></w:p></w:txbxContent></w:{shape_tag}></w:r></w:p>"
        )
    )
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), saved_document(document), "input.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


def set_encryption_flag(content: bytearray, offset: int) -> None:
    flags: int = int.from_bytes(content[offset : offset + 2], "little")
    content[offset : offset + 2] = (flags | 1).to_bytes(2, "little")


def encrypted_entry(content: bytes, filename: str) -> bytes:
    modified: bytearray = bytearray(content)
    archive: ZipFile
    with ZipFile(BytesIO(content)) as archive:
        entry: ZipInfo = archive.getinfo(filename)
        set_encryption_flag(modified, entry.header_offset + 6)
    end_offset: int = content.rfind(b"PK\x05\x06")
    central_offset: int = int.from_bytes(content[end_offset + 16 : end_offset + 20], "little")
    while content[central_offset : central_offset + 4] == b"PK\x01\x02":
        name_size: int = int.from_bytes(
            content[central_offset + 28 : central_offset + 30], "little"
        )
        extra_size: int = int.from_bytes(
            content[central_offset + 30 : central_offset + 32], "little"
        )
        comment_size: int = int.from_bytes(
            content[central_offset + 32 : central_offset + 34], "little"
        )
        name: str = content[central_offset + 46 : central_offset + 46 + name_size].decode()
        if name == filename:
            set_encryption_flag(modified, central_offset + 8)
            return bytes(modified)
        central_offset += 46 + name_size + extra_size + comment_size
    raise AssertionError("Synthetic ZIP member was not found")


@pytest.mark.parametrize("filename", ["word/document.xml", "[Content_Types].xml"])
def test_encrypted_zip_member_is_rejected_during_upload_validation(filename: str) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("A valid requirement")
    content: bytes = encrypted_entry(saved_document(document), filename)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().validate(content, "input.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


@pytest.mark.parametrize("filename", ["word/document.xml", "[Content_Types].xml"])
def test_encrypted_zip_member_never_escapes_as_runtime_error(filename: str) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("A valid requirement")
    content: bytes = encrypted_entry(saved_document(document), filename)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), content, "input.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT

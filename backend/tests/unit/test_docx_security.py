from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import parse_xml
from docx.section import _Footer, _Header

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.parsers.document_validator import DOCX_MIME


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


def zip_entry_offsets(content: bytes, filename: str) -> tuple[int, int]:
    archive: ZipFile
    with ZipFile(BytesIO(content)) as archive:
        entry: ZipInfo = archive.getinfo(filename)
        local_offset: int = entry.header_offset
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
            return local_offset, central_offset
        central_offset += 46 + name_size + extra_size + comment_size
    raise AssertionError("Synthetic ZIP member was not found")


def encrypted_entry(content: bytes, filename: str) -> bytes:
    modified: bytearray = bytearray(content)
    local_offset: int
    central_offset: int
    local_offset, central_offset = zip_entry_offsets(content, filename)
    set_encryption_flag(modified, local_offset + 6)
    set_encryption_flag(modified, central_offset + 8)
    return bytes(modified)


def unsupported_compression_entry(content: bytes, filename: str) -> bytes:
    modified: bytearray = bytearray(content)
    local_offset: int
    central_offset: int
    local_offset, central_offset = zip_entry_offsets(content, filename)
    modified[local_offset + 8 : local_offset + 10] = (99).to_bytes(2, "little")
    modified[central_offset + 10 : central_offset + 12] = (99).to_bytes(2, "little")
    return bytes(modified)


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


@pytest.mark.parametrize("filename", ["word/document.xml", "[Content_Types].xml"])
def test_unsupported_docx_compression_is_rejected_during_upload_validation(filename: str) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("A valid requirement")
    content: bytes = unsupported_compression_entry(saved_document(document), filename)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().validate(content, "input.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


@pytest.mark.parametrize("filename", ["word/document.xml", "[Content_Types].xml"])
def test_unsupported_docx_compression_never_escapes_as_not_implemented(filename: str) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("A valid requirement")
    content: bytes = unsupported_compression_entry(saved_document(document), filename)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), content, "input.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_stored_and_deflated_docx_are_supported(compression: int) -> None:
    document: DocxDocument = Document()
    document.add_paragraph("The system shall preserve this requirement.")
    original: bytes = saved_document(document)
    output: BytesIO = BytesIO()
    source: ZipFile
    target: ZipFile
    with (
        ZipFile(BytesIO(original)) as source,
        ZipFile(output, "w", compression=compression) as target,
    ):
        entry: ZipInfo
        for entry in source.infolist():
            target.writestr(entry.filename, source.read(entry.filename))
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), output.getvalue(), "input.docx", DOCX_MIME
    )
    assert parsed.text == "The system shall preserve this requirement."

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from pypdf import PdfWriter

from solution_architect_ai.application.document_errors import DocumentErrorCode, DocumentFailure
from solution_architect_ai.domain.documents import DocumentFragment, LocatorKind, ParsedDocument
from solution_architect_ai.infrastructure.document_parser import DOCX_MIME, DocumentParser


def docx_bytes(document: DocxDocument) -> bytes:
    output: BytesIO = BytesIO()
    document.save(output)
    return output.getvalue()


def test_docx_paragraph_table_and_nested_table_are_all_citable() -> None:
    document: DocxDocument = Document()
    document.add_heading("Data", 1)
    document.add_paragraph("Keep data for seven days.")
    table: Table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Field"
    table.cell(0, 1).text = "Rule"
    table.cell(1, 0).text = "Amount"
    table.cell(1, 1).text = "Required"
    nested: Table = table.cell(1, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "Nonnegative"
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), docx_bytes(document), "brd.docx", DOCX_MIME
    )
    assert "Keep data for seven days." in parsed.text
    assert "Amount" in parsed.text
    assert "Required" in parsed.text
    assert "Nonnegative" in parsed.text
    cells: list[DocumentFragment] = [
        item for item in parsed.fragments if item.locator.kind == LocatorKind.TABLE_CELL
    ]
    assert all("/row/" in item.locator.path and "/cell/" in item.locator.path for item in cells)
    assert all(item.locator.section.startswith("Data") for item in parsed.fragments)
    assert any(
        "column 2: Rule" in item.locator.section and item.text == "Required" for item in cells
    )


def test_docx_header_requirement_is_rejected_instead_of_omitted() -> None:
    document: DocxDocument = Document()
    document.add_paragraph("Body requirement")
    document.sections[0].header.paragraphs[0].text = "Critical requirement in header"
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), docx_bytes(document), "brd.docx", DOCX_MIME)
    assert error.value.code == DocumentErrorCode.UNSUPPORTED_CONTENT


def test_scanned_pdf_is_not_a_successful_empty_parse() -> None:
    writer: PdfWriter = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output: BytesIO = BytesIO()
    writer.write(output)
    with pytest.raises(DocumentFailure) as error:
        DocumentParser().parse(uuid4(), uuid4(), output.getvalue(), "scan.pdf", "application/pdf")
    assert error.value.code == DocumentErrorCode.NO_TEXT


def test_example_pdf_preserves_page_and_table_source_lines() -> None:
    source: Path = Path(__file__).parents[3] / "docs" / "pdf" / "example.pdf"
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), source.read_bytes(), "example.pdf", "application/pdf"
    )
    assert "pdf_layout_and_tables_require_manual_review" in parsed.warnings
    assert any(item.locator.start == 2 and "R-01" in item.text for item in parsed.fragments)
    assert any(item.locator.start == 2 and "N-01" in item.text for item in parsed.fragments)
    assert all(
        item.locator.kind == LocatorKind.PAGE and item.locator.path.startswith("page/")
        for item in parsed.fragments
    )


def test_markdown_fence_does_not_create_a_heading() -> None:
    parsed: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), b"# Real\n```\n# Fake\n```\nRequirement", "a.md", "text/markdown"
    )
    assert parsed.fragments[-1].locator.section == "Real"

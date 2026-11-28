from pathlib import Path
from typing import Final
from uuid import UUID

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.context_models import ContextFragment, ContextPart
from solution_architect_ai.application.models.extraction_models import Evidence, SourceRef
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument
from solution_architect_ai.domain.requirements import EvidenceStatus
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser

FILE_ID: Final[UUID] = UUID("30000000-0000-4000-8000-000000000001")
VERSION_ID: Final[UUID] = UUID("30000000-0000-4000-8000-000000000002")


def test_pdf_r04_saved_page_references_keep_exact_quotes_and_stable_ids() -> None:
    source: Path = Path(__file__).parents[3] / "docs/pdf/example.pdf"
    document: ParsedDocument = DocumentParser().parse(
        FILE_ID, VERSION_ID, source.read_bytes(), source.name, "application/pdf"
    )
    row: tuple[DocumentFragment, ...] = tuple(
        fragment
        for fragment in document.fragments
        if fragment.locator.path in {f"page/2/line/{index}" for index in range(41, 45)}
    )
    part: ContextPart = ContextPart(
        "pdf-r04",
        tuple(
            ContextFragment(
                FILE_ID,
                VERSION_ID,
                document.sha256,
                fragment.fragment_id,
                fragment.locator,
                fragment.text,
                0,
                len(fragment.text),
            )
            for fragment in row
        ),
        (),
        0,
    )
    assert len(row) == 4
    assert row[0].fragment_id == UUID("fdaab787-9950-59ce-8885-3c68ba13daa9")
    assert row[0].text.startswith("R-04")
    assert "допустимом диапазоне" in row[-1].text
    fragment: DocumentFragment
    for fragment in row:
        reference: SourceRef = verify_evidence(
            Evidence(fragment_id=str(fragment.fragment_id), quote=fragment.text), part
        )
        assert reference.status == EvidenceStatus.VERIFIED
        assert reference.quote == fragment.text
        assert reference.version_id == VERSION_ID
        assert reference.sha256 == document.sha256
        assert reference.locator is not None
        assert reference.locator.start == reference.locator.end == 2
        assert reference.locator.path == fragment.locator.path
    combined: SourceRef = verify_evidence(
        Evidence(fragment_id=str(row[0].fragment_id), quote="\n".join(item.text for item in row)),
        part,
    )
    assert combined.status == EvidenceStatus.UNVERIFIED
    assert combined.reason == "quote_not_in_context"

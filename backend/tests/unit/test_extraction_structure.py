from typing import Final
from uuid import uuid4

import pytest

from solution_architect_ai.application.agents.extraction_result_mapper import verify_result
from solution_architect_ai.application.context.context_models import ContextPack, ContextPolicy
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedRequirement,
    PartResult,
    RequirementsExtraction,
)
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser

REQUIREMENT_ROW: Final[str] = "| R-01 | The service shall keep audit entries. |"


@pytest.mark.parametrize("delimiter", ["|---|---|", "| :--- | ---: |", "--- | :---:"])
def test_table_markup_does_not_become_requirement_candidates(delimiter: str) -> None:
    content: bytes = f"| ID | Requirement |\n{delimiter}\n{REQUIREMENT_ROW}\n".encode()
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), content, "requirements.md", "text/markdown"
    )
    original_fragments: tuple[DocumentFragment, ...] = document.fragments
    context: ContextPack = ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, 6912, 256)
    ).build((document,), "")

    result: PartResult = extracted_rows(context)

    assert [requirement.original_text for requirement in result.requirements] == [REQUIREMENT_ROW]
    assert context.total_fragments == 3
    assert "| ID | Requirement |" in context.parts[0].messages[-1].content
    assert document.text.encode() == content
    assert document.fragments == original_fragments
    assert len(document.fragments) == 3


def extracted_rows(context: ContextPack, part_index: int = 0) -> PartResult:
    candidates: RequirementsExtraction = RequirementsExtraction(
        requirements=[
            ExtractedRequirement(
                category="functional",
                original_text=fragment.text,
                normalized_text=fragment.text,
                evidence=[Evidence(fragment_id=str(fragment.fragment_id), quote=fragment.text)],
            )
            for fragment in context.parts[part_index].fragments
        ],
        gaps=[],
        contradictions=[],
    )
    return verify_result(candidates, context.parts[part_index])


@pytest.mark.parametrize(
    "statement",
    [
        "The value A | B shall be accepted.",
        "| R-01 | The service shall accept --- as input. |",
        "## The service shall keep audit entries",
    ],
)
def test_nonstructural_pipe_and_heading_content_remains_available(statement: str) -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), statement.encode(), "requirements.md", "text/markdown"
    )
    context: ContextPack = ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, 6912, 256)
    ).build((document,), "")

    assert [fragment.text for part in context.parts for fragment in part.fragments] == [statement]
    assert len(extracted_rows(context).requirements) == 1


def test_header_recognition_survives_splitting_and_window_boundaries() -> None:
    header: str = "| " + "Identifier " * 250 + "| Requirement |"
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        f"{header}\n|---|---|\n{REQUIREMENT_ROW}".encode(),
        "requirements.md",
        "text/markdown",
    )
    context: ContextPack = ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, 1200, 256)
    ).build((document,), "")

    assert len(context.parts) > 1
    assert context.total_fragments == 3
    assert [
        requirement.original_text
        for index in range(len(context.parts))
        for requirement in extracted_rows(context, index).requirements
    ] == [REQUIREMENT_ROW]


def test_requirement_supported_by_data_row_and_header_is_retained() -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        f"| ID | Requirement |\n|---|---|\n{REQUIREMENT_ROW}".encode(),
        "requirements.md",
        "text/markdown",
    )
    context: ContextPack = ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False), ContextPolicy(12288, 6912, 256)
    ).build((document,), "")
    candidate: ExtractedRequirement = ExtractedRequirement(
        category="functional",
        original_text=REQUIREMENT_ROW,
        normalized_text="The service shall keep audit entries.",
        evidence=[
            Evidence(fragment_id=str(fragment.fragment_id), quote=fragment.text)
            for fragment in (document.fragments[0], document.fragments[2])
        ],
    )
    result: PartResult = verify_result(
        RequirementsExtraction(requirements=[candidate], gaps=[], contradictions=[]),
        context.parts[0],
    )

    assert len(result.requirements) == 1
    assert len(result.requirements[0].sources) == 2
    assert all(source.status.value == "verified" for source in result.requirements[0].sources)

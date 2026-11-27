from typing import Final
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.context_models import (
    ContextPack,
    ContextPart,
    ContextPolicy,
)
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.errors.extraction_errors import ContextTooLarge
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedRequirement,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import StructuredMode
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser

HASH: Final[str] = "a" * 64


class CharacterCounter:
    def count(self, messages: list[MessageView]) -> int:
        return sum(len(message.content) for message in messages) + 12 * len(messages)


def parsed(text: str) -> ParsedDocument:
    return ParsedDocument(
        file_id=uuid4(),
        version_id=uuid4(),
        sha256=HASH,
        parser_version="test-1",
        text=text,
        fragments=(DocumentFragment(uuid4(), text, SourceLocator(LocatorKind.LINES, 1, 2)),),
        warnings=(),
    )


def test_context_covers_every_character_and_keeps_sources_in_user_message() -> None:
    document: ParsedDocument = parsed("# Sales\n" + "Sales must be retained.\n" * 500)
    builder: ExtractionContextBuilder = ExtractionContextBuilder(
        CharacterCounter(), ContextPolicy(6500, 512, 64)
    )
    pack: ContextPack = builder.build((document,), "reporting")
    assert len(pack.parts) > 1
    assert "".join(piece.text for part in pack.parts for piece in part.fragments) == document.text
    assert pack.total_fragments == 1
    assert all(part.token_estimate + 512 + 64 <= 6500 for part in pack.parts)
    assert all(document.text[:8] not in part.messages[0].content for part in pack.parts)
    assert all(part.messages[-1].role.value == "user" for part in pack.parts)
    assert builder.build((document,), "reporting").digest == pack.digest


def test_context_rejects_schema_and_prompt_that_leave_no_room() -> None:
    with pytest.raises(ContextTooLarge):
        ExtractionContextBuilder(CharacterCounter(), ContextPolicy(600, 450, 64)).build(
            (parsed("BRD"),), ""
        )


def test_source_requires_quote_in_the_exact_sent_slice_and_known_id() -> None:
    document: ParsedDocument = parsed("Allowed quotation.\n" + "Other evidence.\n" * 500)
    pack: ContextPack = ExtractionContextBuilder(
        CharacterCounter(), ContextPolicy(6500, 512, 64)
    ).build((document,), "")
    first: ContextPart = pack.parts[0]
    fragment_id: UUID = document.fragments[0].fragment_id
    valid: SourceRef = verify_evidence(
        Evidence(fragment_id=str(fragment_id), quote="Allowed quotation."), first
    )
    assert valid.status == "verified"
    assert valid.version_id == document.version_id
    invented: SourceRef = verify_evidence(
        Evidence(fragment_id=str(uuid4()), quote="Allowed quotation."), first
    )
    assert invented.status == "unverified"
    assert invented.reason == "fragment_not_in_context"
    absent: SourceRef = verify_evidence(
        Evidence(fragment_id=str(fragment_id), quote="Invented quotation"), first
    )
    assert absent.status == "unverified"
    assert absent.reason == "quote_not_in_context"


def test_requirement_schema_rejects_extra_fields_and_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        ExtractedRequirement.model_validate(
            {
                "category": RequirementCategory.FUNCTIONAL.value,
                "original_text": "Original",
                "normalized_text": "Normalized",
                "evidence": [],
                "approved": True,
            }
        )


def test_context_partitions_for_response_budget_even_when_input_would_fit() -> None:
    document: ParsedDocument = parsed("Система должна сохранять все отчёты.\n" * 20)
    builder: ExtractionContextBuilder = ExtractionContextBuilder(
        CharacterCounter(), ContextPolicy(20000, 512, 64)
    )
    pack: ContextPack = builder.build((document,), "BRD")
    assert len(pack.parts) > 1
    assert "".join(piece.text for part in pack.parts for piece in part.fragments) == document.text
    assert all(builder.response_estimate(part.fragments) + 64 <= 512 for part in pack.parts)


def test_small_document_keeps_sections_and_contradictions_in_one_request() -> None:
    text: str = "\n".join(
        (
            "# Бронирования",
            "Сотрудник должен бронировать переговорные.",
            "## Хранение",
            "История должна храниться не менее 30 дней.",
            "## Удаление",
            "История должна полностью удаляться не позднее 7 дней.",
        )
    )
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), text.encode(), "BRD.md", "text/markdown"
    )
    builder: ExtractionContextBuilder = ExtractionContextBuilder(
        LangChainTokenCounter(2, chat_prompt=False),
        ContextPolicy(12288, 6912, 256, StructuredMode.NATIVE_JSON_SCHEMA, 2),
    )
    pack: ContextPack = builder.build((document,), "Бронирования")
    assert len(pack.parts) == 1
    assert len(pack.parts[0].fragments) == len(document.fragments)
    assert not pack.warnings


@pytest.mark.parametrize(
    ("context_window", "output_limit", "service_tokens", "correction_retries"),
    [(100, 100, 0, 1), (100, 30, 30, 1), (100, 30, -1, 1), (100, 30, 0, -1)],
)
def test_invalid_context_policy_is_a_configuration_error(
    context_window: int, output_limit: int, service_tokens: int, correction_retries: int
) -> None:
    with pytest.raises(ValueError, match="context policy"):
        ContextPolicy(
            context_window, output_limit, service_tokens, correction_retries=correction_retries
        )


class MeasuredCounter(CharacterCounter):
    def __init__(self) -> None:
        self.characters: int = 0

    def count(self, messages: list[MessageView]) -> int:
        self.characters += sum(len(message.content) for message in messages)
        return super().count(messages)


def test_whole_document_grouping_does_not_retokenize_every_growing_prefix() -> None:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        ("The system shall retain records.\n" * 120).encode(),
        "BRD.txt",
        "text/plain",
    )
    counter: MeasuredCounter = MeasuredCounter()
    builder: ExtractionContextBuilder = ExtractionContextBuilder(
        counter, ContextPolicy(1_000_000, 100_000, 64)
    )
    pack: ContextPack = builder.build((document,), "")
    assert len(pack.parts) == 1
    # Input and response checks per source, plus a bounded number of full-pack checks.
    assert counter.characters < 1_500_000

from typing import Final
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.extraction_context import (
    ContextBuilder,
    ContextPack,
    ContextPart,
    ContextPolicy,
)
from solution_architect_ai.application.extraction_errors import ContextTooLarge
from solution_architect_ai.application.extraction_models import (
    Evidence,
    ExtractedRequirement,
    SourceRef,
)
from solution_architect_ai.application.extraction_sources import verify_evidence
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory

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
    builder: ContextBuilder = ContextBuilder(CharacterCounter(), ContextPolicy(6500, 512, 64))
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
        ContextBuilder(CharacterCounter(), ContextPolicy(512, 450, 64)).build((parsed("BRD"),), "")


def test_source_requires_quote_in_the_exact_sent_slice_and_known_id() -> None:
    document: ParsedDocument = parsed("Allowed quotation.\n" + "Other evidence.\n" * 500)
    pack: ContextPack = ContextBuilder(CharacterCounter(), ContextPolicy(6500, 512, 64)).build(
        (document,), ""
    )
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
    builder: ContextBuilder = ContextBuilder(CharacterCounter(), ContextPolicy(20000, 512, 64))
    pack: ContextPack = builder.build((document,), "BRD")
    assert len(pack.parts) > 1
    assert "".join(piece.text for part in pack.parts for piece in part.fragments) == document.text
    assert all(builder.response_estimate(part.fragments) + 64 <= 512 for part in pack.parts)

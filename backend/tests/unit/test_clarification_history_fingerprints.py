from dataclasses import replace
from uuid import uuid4

import pytest

from solution_architect_ai.application.context.clarification_history import fragment_fingerprints
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.domain.documents import LocatorKind, SourceLocator


def whole_fragment() -> ContextFragment:
    text: str = "Reports retain their original source."
    return ContextFragment(
        uuid4(),
        uuid4(),
        "a" * 64,
        uuid4(),
        SourceLocator(LocatorKind.LINES, 1, 1),
        text,
        0,
        len(text),
    )


def test_fragment_fingerprint_is_independent_of_chunk_boundaries() -> None:
    whole: ContextFragment = whole_fragment()
    first: ContextFragment = replace(whole, text=whole.text[:12])
    second: ContextFragment = replace(whole, text=whole.text[12:], offset=12)
    assert fragment_fingerprints((whole,)) == fragment_fingerprints((first, second))
    assert fragment_fingerprints((whole,)) == fragment_fingerprints((second, first, first))


@pytest.mark.parametrize("different_file", [False, True])
def test_fragment_fingerprint_distinguishes_content_and_document_scope(
    different_file: bool,
) -> None:
    whole: ContextFragment = whole_fragment()
    changed: ContextFragment = (
        replace(whole, file_id=uuid4())
        if different_file
        else replace(whole, text=whole.text.replace("original", "modified"))
    )
    assert fragment_fingerprints((whole,)) != fragment_fingerprints((changed,))


@pytest.mark.parametrize("trailing_missing", [False, True])
def test_incomplete_fragment_slices_cannot_match_complete_source(trailing_missing: bool) -> None:
    whole: ContextFragment = whole_fragment()
    first: ContextFragment = replace(whole, text=whole.text[:12])
    second: ContextFragment = replace(whole, text=whole.text[12:], offset=13)
    pieces: tuple[ContextFragment, ...] = (first,) if trailing_missing else (first, second)
    assert fragment_fingerprints((whole,)) != fragment_fingerprints(pieces)

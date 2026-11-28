from collections.abc import Mapping
from typing import Final

import pytest
from markdown_it import MarkdownIt

from solution_architect_ai.application.context.discussion_citations import DiscussionCitationStream

REFERENCES: Final[Mapping[str, str]] = {
    "f0": "/documents?version=version-a&fragment=fragment-a&run=analysis-b"
}


@pytest.mark.parametrize("split", range(1, 25))
def test_server_resolves_a_context_reference_across_stream_boundaries(split: int) -> None:
    text: str = "Exact quote [source](ref:f0). Unknown [forged](ref:f99)."
    stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    result: str = (
        stream.feed(text[:split]) + stream.feed(text[split:]) + stream.feed("", final=True)
    )
    assert (
        result
        == "Exact quote [source](/documents?version=version-a&fragment=fragment-a&run=analysis-b). Unknown forged."
    )


def test_labels_from_another_context_cannot_create_a_source_link() -> None:
    stream: DiscussionCitationStream = DiscussionCitationStream({})
    assert (
        stream.feed('[source](ref:f0) [malformed](ref:f0 "title")', final=True)
        == "source malformed"
    )


def test_ordinary_chat_does_not_interpret_context_labels() -> None:
    stream: DiscussionCitationStream = DiscussionCitationStream(None)
    assert stream.feed("[literal](ref:f0)") == "[literal](ref:f0)"


@pytest.mark.parametrize(
    "target", ["/documents?version=forged&fragment=forged", "https://example.org/forged"]
)
def test_bound_discussion_does_not_trust_model_constructed_links(target: str) -> None:
    stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    assert stream.feed(f"[invented]({target})", final=True) == "invented"
    assert stream.feed(target, final=True) == f"`{target}`"


@pytest.mark.parametrize(
    "text",
    [
        "See https://example.org/forged now.",
        "See <https://example.org/forged> now.",
        "See http://example.org/forged now.",
        "See /documents?version=forged now.",
        "See /requirements?requirement=forged now.",
        "See [source](ref:f0) and [unknown](ref:f99).",
        f"See {REFERENCES['f0']} now.",
        f"See {REFERENCES['f0']}&forged=true now.",
    ],
)
def test_citation_output_is_independent_of_every_stream_split(text: str) -> None:
    expected: str = DiscussionCitationStream(REFERENCES).feed(text, final=True)
    split: int
    for split in range(len(text) + 1):
        stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
        actual: str = (
            stream.feed(text[:split]) + stream.feed(text[split:]) + stream.feed("", final=True)
        )
        assert actual == expected, f"split={split}"
    character_stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    chunks: list[str] = []
    character: str
    for character in text:
        chunks.append(character_stream.feed(character))
    chunks.append(character_stream.feed("", final=True))
    assert "".join(chunks) == expected


@pytest.mark.parametrize("prefix", ["https", "http", "/documents", "/requirements"])
def test_forged_autolink_is_inactive_when_its_prefix_crosses_a_chunk(prefix: str) -> None:
    suffix: str = "://example.org/forged" if prefix.startswith("http") else "?id=forged"
    stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    result: str = stream.feed(f"<{prefix}") + stream.feed(f"{suffix}>", final=True)
    assert "<a " not in MarkdownIt().render(result)


def test_plain_discussion_text_streams_before_completion() -> None:
    stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    assert stream.feed("Ordinary response ") == "Ordinary response "
    assert stream.feed("continues. ") == "continues. "
    assert stream.feed("", final=True) == ""


@pytest.mark.parametrize("prefix", ["[", "https://example.org/", "/documents?"])
def test_unfinished_citation_buffer_is_bounded_and_cannot_create_a_link(prefix: str) -> None:
    stream: DiscussionCitationStream = DiscussionCitationStream(REFERENCES)
    output: list[str] = [stream.feed(prefix)]
    index: int
    for index in range(20):
        output.append(stream.feed("a" * 1000))
        assert len(stream.pending) <= 8192, index
    output.append(stream.feed(")(https://example.org/forged)>", final=True))
    assert "<a " not in MarkdownIt().render("".join(output))

from collections.abc import Iterable
from typing import Final
from uuid import UUID, uuid5

from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.domain.documents import DocumentFragment, SourceLocator

PARSER_VERSION: Final[str] = "documents-v1"
MAX_PARSED_CHARACTERS: Final[int] = 2_000_000
MAX_FRAGMENTS: Final[int] = 20_000


def fragment(version_id: UUID, text: str, locator: SourceLocator) -> DocumentFragment:
    identity: str = f"{PARSER_VERSION}/{locator.kind}/{locator.start}/{locator.end}/{locator.path}"
    return DocumentFragment(uuid5(version_id, identity), text, locator)


def check_parse_size(characters: int, fragments: int) -> None:
    if characters > MAX_PARSED_CHARACTERS or fragments > MAX_FRAGMENTS:
        raise DocumentFailure(DocumentErrorCode.TOO_LARGE)


def collect_fragments(items: Iterable[DocumentFragment]) -> tuple[DocumentFragment, ...]:
    collected: list[DocumentFragment] = []
    size: int = 0
    item: DocumentFragment
    for item in items:
        size += len(item.text)
        check_parse_size(size, len(collected) + 1)
        collected.append(item)
    return tuple(collected)

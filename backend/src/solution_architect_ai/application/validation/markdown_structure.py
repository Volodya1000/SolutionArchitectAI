import re
from typing import Final

from solution_architect_ai.domain.documents import DocumentFragment, LocatorKind, ParsedDocument

_ALIGNMENT_CELL: Final[re.Pattern[str]] = re.compile(r":?-{3,}:?")


def table_cells(text: str) -> list[str]:
    if "|" not in text or "\n" in text:
        return []
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", text.strip().strip("|"))]


def is_preceding_header(
    header: DocumentFragment, delimiter: DocumentFragment, cell_count: int
) -> bool:
    return (
        delimiter.locator.kind == header.locator.kind == LocatorKind.LINES
        and header.locator.end + 1 == delimiter.locator.start
        and len(table_cells(header.text)) == cell_count
    )


def table_alignment_cells(text: str) -> list[str]:
    cells: list[str] = table_cells(text)
    return cells if cells and all(_ALIGNMENT_CELL.fullmatch(cell) for cell in cells) else []


def structural_fragment_ids(document: ParsedDocument) -> frozenset[str]:
    """Recognize table presentation from the complete source before windowing it."""
    structural: set[str] = set()
    index: int
    fragment: DocumentFragment
    for index, fragment in enumerate(document.fragments):
        cells: list[str] = table_alignment_cells(fragment.text)
        if not cells:
            continue
        structural.add(str(fragment.fragment_id))
        if index == 0:
            continue
        previous: DocumentFragment = document.fragments[index - 1]
        if is_preceding_header(previous, fragment, len(cells)):
            structural.add(str(previous.fragment_id))
    return frozenset(structural)

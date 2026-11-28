from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    MarkdownTable,
    ParsedDocument,
)


def structural_fragment_ids(document: ParsedDocument) -> frozenset[str]:
    """Use parser-recognized syntax; literal TXT and fenced code have no tables."""
    return frozenset(
        str(fragment.fragment_id)
        for fragment in document.fragments
        if document.structure is not None
        and fragment.locator.kind == LocatorKind.LINES
        and any(
            fragment.locator.start in (table.header_line, table.delimiter_line)
            for table in document.structure.tables
        )
    )


def separator_fragment_ids(document: ParsedDocument) -> frozenset[str]:
    return frozenset(
        str(fragment.fragment_id)
        for fragment in document.fragments
        if document.structure is not None
        and fragment.locator.kind == LocatorKind.LINES
        and any(
            fragment.locator.start == table.delimiter_line for table in document.structure.tables
        )
    )


def table_header(document: ParsedDocument, fragment: DocumentFragment) -> str:
    if document.structure is None or fragment.locator.kind != LocatorKind.LINES:
        return ""
    table: MarkdownTable
    for table in document.structure.tables:
        if table.delimiter_line < fragment.locator.start <= table.end_line:
            return table.header_text
    return ""


def table_header_fragments(
    document: ParsedDocument,
    fragment: DocumentFragment,
) -> tuple[DocumentFragment, ...]:
    if document.structure is None or fragment.locator.kind != LocatorKind.LINES:
        return ()
    header_lines: set[int] = {
        table.header_line
        for table in document.structure.tables
        if table.delimiter_line < fragment.locator.start <= table.end_line
    }
    return tuple(
        item
        for item in document.fragments
        if item.locator.kind == LocatorKind.LINES and item.locator.start in header_lines
    )

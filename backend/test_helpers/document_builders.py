from typing import Final
from uuid import UUID, uuid4

from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)

ORIGINAL: Final[str] = "Система должна хранить отчёты."


def document(file_id: UUID, text: str = ORIGINAL) -> ParsedDocument:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(), text, SourceLocator(LocatorKind.LINES, 1, 1)
    )
    return ParsedDocument(file_id, uuid4(), uuid4().hex * 2, "test", text, (fragment,))

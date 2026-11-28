from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LocatorKind(StrEnum):
    LINES = "lines"
    PAGE = "page"
    PARAGRAPH = "paragraph"
    TABLE_CELL = "table_cell"


@dataclass(frozen=True)
class SourceLocator:
    kind: LocatorKind
    start: int
    end: int
    section: str = ""
    path: str = ""


@dataclass(frozen=True)
class DocumentFragment:
    fragment_id: UUID
    text: str
    locator: SourceLocator


@dataclass(frozen=True)
class MarkdownTable:
    header_line: int
    delimiter_line: int
    end_line: int
    header_text: str = ""


@dataclass(frozen=True)
class DocumentStructure:
    tables: tuple[MarkdownTable, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    file_id: UUID
    version_id: UUID
    sha256: str
    parser_version: str
    text: str
    fragments: tuple[DocumentFragment, ...]
    warnings: tuple[str, ...] = ()
    structure: DocumentStructure | None = None


@dataclass(frozen=True)
class Document:
    file_id: UUID
    task_id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True)
class DocumentVersion:
    file_id: UUID
    version_id: UUID
    task_id: UUID
    sha256: str
    mime_type: str
    size: int
    original_name: str
    uploaded_at: datetime
    storage_key: str

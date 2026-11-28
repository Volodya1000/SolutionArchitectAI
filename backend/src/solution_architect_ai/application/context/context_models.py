from dataclasses import dataclass, field
from uuid import UUID

from solution_architect_ai.application.models.structured_models import (
    StructuredMessage,
    StructuredMode,
)
from solution_architect_ai.domain.documents import SourceLocator


@dataclass(frozen=True)
class ContextPolicy:
    context_window: int
    output_limit: int
    service_tokens: int
    mode: StructuredMode = StructuredMode.JSON_TEXT
    correction_retries: int = 2

    def __post_init__(self) -> None:
        if (
            self.service_tokens < 0
            or self.correction_retries < 0
            or self.output_limit <= self.service_tokens
            or self.context_window <= self.output_limit + self.service_tokens
        ):
            raise ValueError("Invalid context policy: input and output budgets must be positive")


@dataclass(frozen=True)
class ContextFragment:
    file_id: UUID
    version_id: UUID
    sha256: str
    fragment_id: UUID
    locator: SourceLocator
    text: str
    offset: int
    total_length: int = 0
    table_header: str = ""


@dataclass(frozen=True)
class ContextPart:
    id: str
    fragments: tuple[ContextFragment, ...]
    messages: tuple[StructuredMessage, ...]
    token_estimate: int
    structural_fragment_ids: frozenset[str] = field(default_factory=frozenset)

    def resolve_source_label(self, identifier: str) -> str:
        labels: dict[str, str] = {
            f"f{index}": str(fragment.fragment_id) for index, fragment in enumerate(self.fragments)
        }
        return labels.get(identifier, identifier)


@dataclass(frozen=True)
class ContextPack:
    digest: str
    parts: tuple[ContextPart, ...]
    total_fragments: int
    warnings: tuple[str, ...]

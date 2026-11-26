import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.extraction_errors import ContextTooLarge
from solution_architect_ai.application.extraction_models import RequirementsExtraction
from solution_architect_ai.application.extraction_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from solution_architect_ai.application.ports import TokenCounter
from solution_architect_ai.application.structured_models import StructuredMessage
from solution_architect_ai.domain.documents import ParsedDocument, SourceLocator
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import CoverageWarning


@dataclass(frozen=True)
class ContextPolicy:
    context_window: int
    output_limit: int
    service_tokens: int


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


@dataclass(frozen=True)
class ContextPart:
    id: str
    fragments: tuple[ContextFragment, ...]
    messages: tuple[StructuredMessage, ...]
    token_estimate: int


@dataclass(frozen=True)
class ContextPack:
    digest: str
    parts: tuple[ContextPart, ...]
    total_fragments: int
    warnings: tuple[str, ...]


class ContextBuilder:
    def __init__(self, tokens: TokenCounter, policy: ContextPolicy) -> None:
        self.tokens: TokenCounter = tokens
        self.policy: ContextPolicy = policy
        self.schema: str = json.dumps(
            RequirementsExtraction.model_json_schema(), sort_keys=True, separators=(",", ":")
        )

    def messages(
        self, fragments: tuple[ContextFragment, ...], scope: str
    ) -> tuple[StructuredMessage, ...]:
        payload: dict[str, object] = {
            "analysis_scope": scope,
            "fragments": [
                {
                    "fragment_id": str(item.fragment_id),
                    "text": item.text,
                    "section": item.locator.section,
                    "path": item.locator.path,
                }
                for item in fragments
            ],
        }
        return (
            StructuredMessage(MessageRole.SYSTEM, SYSTEM_PROMPT),
            StructuredMessage(MessageRole.USER, json.dumps(payload, ensure_ascii=False)),
        )

    def estimate(self, fragments: tuple[ContextFragment, ...], scope: str) -> int:
        messages: tuple[StructuredMessage, ...] = self.messages(fragments, scope)
        views: list[MessageView] = [
            MessageView(
                id=UUID(int=0),
                role=item.role,
                content=item.content,
                position=index,
                incomplete=False,
            )
            for index, item in enumerate(messages)
        ]
        views.append(
            MessageView(
                id=UUID(int=0),
                role=MessageRole.SYSTEM,
                content=self.schema,
                position=2,
                incomplete=False,
            )
        )
        return self.tokens.count(views)

    def fits(self, fragments: tuple[ContextFragment, ...], scope: str) -> bool:
        return (
            self.estimate(fragments, scope)
            <= self.policy.context_window - self.policy.output_limit - self.policy.service_tokens
        )

    def split(self, fragment: ContextFragment, scope: str) -> list[ContextFragment]:
        pieces: list[ContextFragment] = []
        offset: int = 0
        while offset < len(fragment.text):
            low: int = 1
            high: int = len(fragment.text) - offset
            best: int = 0
            while low <= high:
                middle: int = (low + high) // 2
                piece: ContextFragment = self.slice(fragment, offset, middle)
                if self.fits((piece,), scope):
                    best, low = middle, middle + 1
                else:
                    high = middle - 1
            if best == 0:
                raise ContextTooLarge("schema_prompt_output_exceed_context")
            newline: int = fragment.text.rfind("\n", offset, offset + best)
            length: int = newline - offset + 1 if newline > offset else best
            pieces.append(self.slice(fragment, offset, length))
            offset += length
        return pieces

    @staticmethod
    def slice(fragment: ContextFragment, offset: int, length: int) -> ContextFragment:
        return ContextFragment(
            fragment.file_id,
            fragment.version_id,
            fragment.sha256,
            fragment.fragment_id,
            fragment.locator,
            fragment.text[offset : offset + length],
            offset,
            fragment.total_length,
        )

    def build(self, documents: tuple[ParsedDocument, ...], scope: str) -> ContextPack:
        if not documents or not self.fits((), scope):
            raise ContextTooLarge("schema_prompt_output_exceed_context")
        pieces: list[ContextFragment] = self.pieces(documents, scope)
        groups: list[tuple[ContextFragment, ...]] = self.groups(pieces, scope)
        if not groups:
            raise ContextTooLarge("no_text_fragments")
        parts: tuple[ContextPart, ...] = tuple(self.part(group, scope) for group in groups)
        identity: str = json.dumps(
            {
                "prompt": PROMPT_VERSION,
                "prompt_hash": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                "parsers": [(str(doc.version_id), doc.parser_version) for doc in documents],
                "schema": self.schema,
                "scope": scope,
                "parts": [part.id for part in parts],
                "policy": [
                    self.policy.context_window,
                    self.policy.output_limit,
                    self.policy.service_tokens,
                ],
            },
            sort_keys=True,
        )
        warnings: tuple[str, ...] = tuple(warning for doc in documents for warning in doc.warnings)
        if len(parts) > 1:
            warnings = (*warnings, CoverageWarning.CROSS_PART_REVIEW.value)
        return ContextPack(
            sha256(identity.encode()).hexdigest(),
            parts,
            len({piece.fragment_id for piece in pieces}),
            warnings,
        )

    def pieces(self, documents: tuple[ParsedDocument, ...], scope: str) -> list[ContextFragment]:
        pieces: list[ContextFragment] = []
        for document in documents:
            for fragment in document.fragments:
                source: ContextFragment = ContextFragment(
                    document.file_id,
                    document.version_id,
                    document.sha256,
                    fragment.fragment_id,
                    fragment.locator,
                    fragment.text,
                    0,
                    len(fragment.text),
                )
                pieces.extend(
                    [source] if self.fits((source,), scope) else self.split(source, scope)
                )
        return pieces

    def groups(
        self, pieces: list[ContextFragment], scope: str
    ) -> list[tuple[ContextFragment, ...]]:
        groups: list[tuple[ContextFragment, ...]] = []
        current: tuple[ContextFragment, ...] = ()
        for piece in pieces:
            boundary: bool = bool(current) and (
                current[-1].version_id != piece.version_id
                or current[-1].locator.section != piece.locator.section
            )
            if current and (boundary or not self.fits((*current, piece), scope)):
                groups.append(current)
                current = ()
            current = (*current, piece)
        if current:
            groups.append(current)
        return groups

    def part(self, fragments: tuple[ContextFragment, ...], scope: str) -> ContextPart:
        identity: str = "|".join(
            f"{item.version_id}:{item.sha256}:{item.fragment_id}:{item.offset}:{item.locator}:{item.text}"
            for item in fragments
        )
        return ContextPart(
            sha256(identity.encode()).hexdigest(),
            fragments,
            self.messages(fragments, scope),
            self.estimate(fragments, scope),
        )

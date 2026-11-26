import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.extraction_errors import ContextTooLarge
from solution_architect_ai.application.extraction_models import RequirementsExtraction
from solution_architect_ai.application.extraction_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from solution_architect_ai.application.ports import TokenCounter
from solution_architect_ai.application.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.application.structured_prompt import (
    CORRECTION_PROMPT,
    render_messages,
    token_messages,
)
from solution_architect_ai.domain.documents import ParsedDocument, SourceLocator
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import CoverageWarning


@dataclass(frozen=True)
class ContextPolicy:
    context_window: int
    output_limit: int
    service_tokens: int
    mode: StructuredMode = StructuredMode.JSON_TEXT
    correction_retries: int = 2


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
        return self.tokens.count(token_messages(self.rendered(fragments, scope)))

    def rendered(
        self, fragments: tuple[ContextFragment, ...], scope: str
    ) -> tuple[StructuredMessage, ...]:
        messages: tuple[StructuredMessage, ...] = self.messages(fragments, scope)
        profile: ModelProfile = ModelProfile(
            "context",
            self.policy.mode,
            self.policy.context_window,
            self.policy.output_limit,
            self.policy.service_tokens,
        )
        return render_messages(
            StructuredRequest(messages, profile),
            RequirementsExtraction,
            reserve_corrections=self.policy.correction_retries,
            include_native_schema=True,
        )

    def response_estimate(self, fragments: tuple[ContextFragment, ...]) -> int:
        payload: dict[str, object] = {
            "requirements": [
                {
                    "category": "system_boundary",
                    "original_text": item.text,
                    "normalized_text": item.text,
                    "evidence": [{"fragment_id": str(item.fragment_id), "quote": item.text}],
                }
                for item in fragments
            ],
            "gaps": [],
            "contradictions": [],
        }
        sample: MessageView = MessageView(
            id=UUID(int=0),
            role=MessageRole.ASSISTANT,
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            position=0,
            incomplete=False,
        )
        return self.tokens.count([sample])

    def fits(self, fragments: tuple[ContextFragment, ...], scope: str) -> bool:
        return (
            self.estimate(fragments, scope)
            <= self.policy.context_window - self.policy.output_limit - self.policy.service_tokens
            and self.response_estimate(fragments) + self.policy.service_tokens
            <= self.policy.output_limit
        )

    def split(self, fragment: ContextFragment, scope: str) -> list[ContextFragment]:
        pieces: list[ContextFragment] = []
        offset: int = 0
        while offset < len(fragment.text):
            best: int = self.longest_prefix(fragment, offset, scope)
            length: int = self.split_length(fragment.text, offset, best)
            pieces.append(self.slice(fragment, offset, length))
            offset += length
        return pieces

    def longest_prefix(self, fragment: ContextFragment, offset: int, scope: str) -> int:
        low: int = 1
        high: int = min(128, len(fragment.text) - offset)
        while high < len(fragment.text) - offset and self.fits(
            (self.slice(fragment, offset, high),), scope
        ):
            high = min(high * 2, len(fragment.text) - offset)
        best: int = 0
        while low <= high:
            middle: int = (low + high) // 2
            if self.fits((self.slice(fragment, offset, middle),), scope):
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best == 0:
            raise ContextTooLarge("schema_prompt_output_exceed_context")
        return best

    @staticmethod
    def split_length(text: str, offset: int, maximum: int) -> int:
        boundaries: list[int] = []
        delimiter: str
        for delimiter in ("\n", ". ", "; "):
            index: int = text.rfind(delimiter, offset, offset + maximum)
            if index >= offset:
                boundaries.append(index + len(delimiter))
        if boundaries:
            return max(boundaries) - offset
        space: int = text.rfind(" ", offset, offset + maximum)
        return space - offset + 1 if space > offset else maximum

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
                "rendered_prompt_hash": sha256(
                    json.dumps(
                        [(item.role.value, item.content) for item in self.rendered((), scope)],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
                "builder_version": "context-2",
                "parsers": [(str(doc.version_id), doc.parser_version) for doc in documents],
                "schema": self.schema,
                "correction_hash": sha256(CORRECTION_PROMPT.encode()).hexdigest(),
                "scope": scope,
                "parts": [part.id for part in parts],
                "policy": [
                    self.policy.context_window,
                    self.policy.output_limit,
                    self.policy.service_tokens,
                    self.policy.mode.value,
                    self.policy.correction_retries,
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

import json
from collections.abc import Iterator
from dataclasses import asdict
from itertools import groupby
from uuid import UUID

from solution_architect_ai.application.context.context_identity import context_digest, part_digest
from solution_architect_ai.application.context.context_models import (
    ContextFragment,
    ContextPack,
    ContextPart,
    ContextPolicy,
)
from solution_architect_ai.application.context.context_payload import ContextPayload, PromptFragment
from solution_architect_ai.application.context.response_estimator import estimate_response_tokens
from solution_architect_ai.application.errors.extraction_errors import ContextTooLarge
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.extraction_prompt import SYSTEM_PROMPT
from solution_architect_ai.application.prompts.structured_prompt import (
    render_messages,
    token_messages,
)
from solution_architect_ai.application.protocols.chat_protocols import TokenCounter
from solution_architect_ai.application.validation.markdown_structure import (
    separator_fragment_ids,
    structural_fragment_ids,
    table_header,
)
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import CoverageWarning


class ExtractionContextBuilder:
    def __init__(self, token_counter: TokenCounter, context_policy: ContextPolicy) -> None:
        self.token_counter: TokenCounter = token_counter
        self.context_policy: ContextPolicy = context_policy
        self.profile: ModelProfile = ModelProfile(
            "context",
            context_policy.mode,
            context_policy.context_window,
            context_policy.output_limit,
            context_policy.service_tokens,
        )
        self.schema: str = json.dumps(
            RequirementsExtraction.model_json_schema(), sort_keys=True, separators=(",", ":")
        )

    def messages(
        self, fragments: tuple[ContextFragment, ...], scope: str
    ) -> tuple[StructuredMessage, ...]:
        payload: ContextPayload = ContextPayload(
            scope,
            [
                PromptFragment(
                    f"f{index}",
                    item.text,
                    " | ".join(
                        value for value in (item.locator.section, item.table_header) if value
                    ),
                    item.locator.path,
                )
                for index, item in enumerate(fragments)
            ],
        )
        return (
            StructuredMessage(MessageRole.SYSTEM, SYSTEM_PROMPT),
            StructuredMessage(MessageRole.USER, json.dumps(asdict(payload), ensure_ascii=False)),
        )

    def estimate(self, fragments: tuple[ContextFragment, ...], scope: str) -> int:
        return self.token_counter.count(token_messages(self.rendered(fragments, scope)))

    def rendered(
        self, fragments: tuple[ContextFragment, ...], scope: str
    ) -> tuple[StructuredMessage, ...]:
        messages: tuple[StructuredMessage, ...] = self.messages(fragments, scope)
        return render_messages(
            StructuredRequest(messages, self.profile),
            RequirementsExtraction,
            reserve_corrections=self.context_policy.correction_retries,
            include_native_schema=True,
        )

    def response_estimate(self, fragments: tuple[ContextFragment, ...]) -> int:
        return estimate_response_tokens(fragments, self.token_counter)

    def fits(self, fragments: tuple[ContextFragment, ...], scope: str) -> bool:
        return (
            self.estimate(fragments, scope)
            <= self.context_policy.context_window
            - self.context_policy.output_limit
            - self.context_policy.service_tokens
            and self.response_estimate(fragments) + self.context_policy.service_tokens
            <= self.context_policy.output_limit
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
        for delimiter in ("\n", "; "):
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
            fragment.offset + offset,
            fragment.total_length,
            fragment.table_header,
        )

    def build(self, documents: tuple[ParsedDocument, ...], scope: str) -> ContextPack:
        if not documents or not self.fits((), scope):
            raise ContextTooLarge("schema_prompt_output_exceed_context")
        pieces: list[ContextFragment] = self.pieces(documents, scope)
        groups: list[tuple[ContextFragment, ...]] = self.groups(pieces, scope)
        if not groups:
            raise ContextTooLarge("no_text_fragments")
        structural_ids: frozenset[str] = frozenset(
            identifier for document in documents for identifier in structural_fragment_ids(document)
        )
        parts: tuple[ContextPart, ...] = tuple(
            self.part(group, scope, structural_ids) for group in groups
        )
        identity: str = context_digest(
            documents, parts, scope, self.schema, self.context_policy, self.rendered((), scope)
        )
        warnings: tuple[str, ...] = tuple(warning for doc in documents for warning in doc.warnings)
        if len(parts) > 1:
            warnings = (*warnings, CoverageWarning.CROSS_PART_REVIEW.value)
        return ContextPack(
            identity,
            parts,
            sum(len(document.fragments) for document in documents),
            warnings,
        )

    def pieces(self, documents: tuple[ParsedDocument, ...], scope: str) -> list[ContextFragment]:
        pieces: list[ContextFragment] = []
        document: ParsedDocument
        fragment: DocumentFragment
        for document in documents:
            separator_ids: frozenset[str] = separator_fragment_ids(document)
            for fragment in document.fragments:
                if str(fragment.fragment_id) in separator_ids:
                    continue
                source: ContextFragment = ContextFragment(
                    document.file_id,
                    document.version_id,
                    document.sha256,
                    fragment.fragment_id,
                    fragment.locator,
                    fragment.text,
                    0,
                    len(fragment.text),
                    table_header(document, fragment),
                )
                pieces.extend(
                    [source] if self.fits((source,), scope) else self.split(source, scope)
                )
        return pieces

    def groups(
        self, pieces: list[ContextFragment], scope: str
    ) -> list[tuple[ContextFragment, ...]]:
        groups: list[tuple[ContextFragment, ...]] = []
        _version_id: UUID
        document_pieces: Iterator[ContextFragment]
        for _version_id, document_pieces in groupby(pieces, key=lambda item: item.version_id):
            remaining: tuple[ContextFragment, ...] = tuple(document_pieces)
            offset: int = 0
            while offset < len(remaining):
                length: int = self.group_length(remaining, offset, scope)
                groups.append(remaining[offset : offset + length])
                offset += length
        return groups

    def group_length(self, pieces: tuple[ContextFragment, ...], offset: int, scope: str) -> int:
        # Grow geometrically rather than tokenize every growing prefix. The final
        # candidate is always measured by the same exact input/output checks.
        available: int = len(pieces) - offset
        best: int = 1
        high: int = min(2, available)
        while self.fits(pieces[offset : offset + high], scope):
            best = high
            if high == available:
                return best
            high = min(high * 2, available)
        low: int = best + 1
        high -= 1
        while low <= high:
            middle: int = (low + high) // 2
            if self.fits(pieces[offset : offset + middle], scope):
                best, low = middle, middle + 1
            else:
                high = middle - 1
        return best

    def part(
        self,
        fragments: tuple[ContextFragment, ...],
        scope: str,
        structural_ids: frozenset[str] = frozenset(),
    ) -> ContextPart:
        return ContextPart(
            part_digest(fragments),
            fragments,
            self.messages(fragments, scope),
            self.estimate(fragments, scope),
            structural_ids.intersection(str(fragment.fragment_id) for fragment in fragments),
        )

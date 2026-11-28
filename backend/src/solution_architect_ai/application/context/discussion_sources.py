from typing import Final
from uuid import UUID

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.models.discussion_models import DiscussionBinding
from solution_architect_ai.application.models.extraction_models import SourceRef
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.validation.markdown_structure import (
    separator_fragment_ids,
    table_header_fragments,
)
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument

RELATED_CHARACTERS: Final[int] = 16000


class DiscussionSourceContextBuilder:
    def __init__(self, discussion_service: DiscussionService) -> None:
        self.discussion_service: DiscussionService = discussion_service

    async def sources(self, binding: DiscussionBinding) -> tuple[list[SourceRef], int]:
        sources: list[SourceRef] = await self.selected_sources(binding.sources)
        seen: set[str] = {source.fragment_id for source in sources}
        remaining: int = RELATED_CHARACTERS
        document_sizes: dict[UUID | None, int] = {}
        selected: SourceRef
        for selected in binding.sources:
            related: list[SourceRef]
            document_size: int
            related, document_size = await self.related_sources(selected, seen, remaining)
            document_sizes[selected.version_id] = document_size
            sources.extend(related)
            seen.update(source.fragment_id for source in related)
            remaining -= sum(len(source.quote) for source in related)
        return sources, sum(document_sizes.values()) - len(sources)

    async def selected_sources(self, selected_sources: list[SourceRef]) -> list[SourceRef]:
        sources: list[SourceRef] = []
        selected: SourceRef
        for selected in selected_sources:
            sources.append(await self.selected_source(selected))
        return sources

    async def selected_source(self, selected: SourceRef) -> SourceRef:
        if selected.version_id is None:
            raise Missing("source_version")
        document: ParsedDocument = (
            await self.discussion_service.documents_service.get_parsed_document(selected.version_id)
        )
        if selected.fragment_id in separator_fragment_ids(document):
            raise Missing("source_not_semantic")
        exact: SourceRef = await self.discussion_service.source_reference(
            selected.version_id, UUID(selected.fragment_id)
        )
        if exact.sha256 != selected.sha256 or exact.locator != selected.locator:
            raise Missing("source_changed")
        return exact

    async def related_sources(
        self, selected: SourceRef, seen: set[str], remaining: int
    ) -> tuple[list[SourceRef], int]:
        if selected.version_id is None:
            raise Missing("source_version")
        document: ParsedDocument = (
            await self.discussion_service.documents_service.get_parsed_document(selected.version_id)
        )
        index: int = next(
            offset
            for offset, fragment in enumerate(document.fragments)
            if str(fragment.fragment_id) == selected.fragment_id
        )
        sources: list[SourceRef] = []
        separator_ids: frozenset[str] = separator_fragment_ids(document)
        seen = set(seen)
        neighbors: tuple[DocumentFragment, ...] = (
            *table_header_fragments(document, document.fragments[index]),
            *document.fragments[max(0, index - 2) : index + 3],
        )
        fragment: DocumentFragment
        # Nearby fragments preserve same-version context for examples spanning R03/R04.
        for fragment in neighbors:
            if str(fragment.fragment_id) in seen | separator_ids or len(fragment.text) > remaining:
                continue
            sources.append(
                await self.discussion_service.source_reference(
                    selected.version_id, fragment.fragment_id
                )
            )
            seen.add(str(fragment.fragment_id))
            remaining -= len(fragment.text)
        return sources, len(document.fragments)

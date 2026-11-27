import json
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import (
    LocatorView,
    RequirementView,
    SourceRef,
)


def requirement_fingerprint(requirement: RequirementView) -> str:
    payload: tuple[str, str, list[tuple[str, str]]] = (
        requirement.category.value,
        requirement.original_text,
        sorted((str(source.file_id), source.quote) for source in requirement.sources),
    )
    return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def fingerprint_fragment_content(
    file_id: UUID, chunks: list[tuple[int, str]], lengths: set[int]
) -> str:
    expected_offset: int = 0
    content: list[str] = []
    complete: bool = True
    offset: int
    text: str
    for offset, text in sorted(set(chunks)):
        if offset != expected_offset:
            complete = False
        content.append(text)
        expected_offset = offset + len(text)
    complete = complete and all(length in {0, expected_offset} for length in lengths)
    # Incomplete coverage never matches the fingerprint of a complete source.
    payload: tuple[str, str, bool] = (str(file_id), "".join(content), complete)
    return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def fragment_fingerprints(fragments: tuple[ContextFragment, ...]) -> dict[str, str]:
    pieces: dict[UUID, list[tuple[int, str]]] = {}
    scopes: dict[UUID, UUID] = {}
    lengths: dict[UUID, set[int]] = {}
    fragment: ContextFragment
    for fragment in fragments:
        pieces.setdefault(fragment.fragment_id, []).append((fragment.offset, fragment.text))
        scopes[fragment.fragment_id] = fragment.file_id
        lengths.setdefault(fragment.fragment_id, set()).add(fragment.total_length)
    return {
        str(identifier): fingerprint_fragment_content(
            scopes[identifier], chunks, lengths[identifier]
        )
        for identifier, chunks in pieces.items()
    }


def has_changed_source_basis(
    previous: ClarificationQuestion, current: ClarificationQuestion
) -> bool:
    if previous.source_fingerprints and current.source_fingerprints:
        return set(previous.source_fingerprints.values()) != set(
            current.source_fingerprints.values()
        )
    return {(source.file_id, source.quote) for source in previous.sources} != {
        (source.file_id, source.quote) for source in current.sources
    }


class ClarificationHistoryMatcher:
    def __init__(
        self, fragments: tuple[ContextFragment, ...], requirements: tuple[RequirementView, ...]
    ) -> None:
        self.fragments: tuple[ContextFragment, ...] = fragments
        self.source_fingerprints: dict[str, str] = fragment_fingerprints(fragments)
        self.requirement_fingerprints: dict[UUID, str] = {
            requirement.id: requirement_fingerprint(requirement) for requirement in requirements
        }
        self.requirements: dict[str, list[RequirementView]] = {}
        requirement: RequirementView
        for requirement in requirements:
            self.requirements.setdefault(self.requirement_fingerprints[requirement.id], []).append(
                requirement
            )

    def rebind(self, question: ClarificationQuestion) -> ClarificationQuestion | None:
        # Old snapshots without fingerprints cannot establish unchanged applicability.
        if not question.requirement_fingerprints or not question.source_fingerprints:
            return None
        identifiers: list[UUID] = []
        fingerprint: str
        for fingerprint in question.requirement_fingerprints.values():
            matches: list[RequirementView] = self.requirements.get(fingerprint, [])
            if len(matches) != 1:
                return None
            identifiers.append(matches[0].id)
        sources: list[SourceRef] = []
        source: SourceRef
        for source in question.sources:
            rebound: SourceRef | None = self.rebind_source(source, question.source_fingerprints)
            if rebound is None:
                return None
            sources.append(rebound)
        return question.model_copy(
            update={"requirement_ids": identifiers, "sources": sources}, deep=True
        )

    def rebind_source(self, source: SourceRef, fingerprints: dict[str, str]) -> SourceRef | None:
        fingerprint: str | None = fingerprints.get(source.fragment_id)
        matches: dict[UUID, ContextFragment] = {
            fragment.fragment_id: fragment
            for fragment in self.fragments
            if fingerprint is not None
            and self.source_fingerprints[str(fragment.fragment_id)] == fingerprint
            and source.quote in fragment.text
        }
        if len(matches) != 1:
            return None
        fragment: ContextFragment = next(iter(matches.values()))
        return source.model_copy(
            update={
                "file_id": fragment.file_id,
                "version_id": fragment.version_id,
                "sha256": fragment.sha256,
                "fragment_id": str(fragment.fragment_id),
                "locator": LocatorView(
                    kind=fragment.locator.kind.value,
                    start=fragment.locator.start,
                    end=fragment.locator.end,
                    section=fragment.locator.section,
                    path=fragment.locator.path,
                ),
            }
        )

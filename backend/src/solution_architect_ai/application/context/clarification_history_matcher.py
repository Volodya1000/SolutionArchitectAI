from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.context.source_fingerprints import (
    fragment_fingerprints,
    requirement_fingerprint,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import (
    LocatorView,
    RequirementView,
    SourceRef,
)


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
        rebound_question: ClarificationQuestion = question.model_copy(deep=True)
        rebound_question.requirement_ids = identifiers
        rebound_question.sources = sources
        rebound_question.requirement_fingerprints = {
            identifier: self.requirement_fingerprints[identifier] for identifier in identifiers
        }
        rebound_question.source_fingerprints = {
            source.fragment_id: self.source_fingerprints[source.fragment_id] for source in sources
        }
        return rebound_question

    def source_text(self, fragment_id: UUID) -> str:
        chunks: list[tuple[int, str]] = sorted(
            {
                (fragment.offset, fragment.text)
                for fragment in self.fragments
                if fragment.fragment_id == fragment_id
            }
        )
        return "".join(text for _, text in chunks)

    def rebind_source(self, source: SourceRef, fingerprints: dict[str, str]) -> SourceRef | None:
        fingerprint: str | None = fingerprints.get(source.fragment_id)
        matches: dict[UUID, ContextFragment] = {
            fragment.fragment_id: fragment
            for fragment in self.fragments
            if fingerprint is not None
            and self.source_fingerprints[str(fragment.fragment_id)] == fingerprint
            and source.quote in self.source_text(fragment.fragment_id)
        }
        if len(matches) != 1:
            return None
        fragment: ContextFragment = next(iter(matches.values()))
        return SourceRef(
            file_id=fragment.file_id,
            version_id=fragment.version_id,
            sha256=fragment.sha256,
            fragment_id=str(fragment.fragment_id),
            locator=LocatorView(
                kind=fragment.locator.kind.value,
                start=fragment.locator.start,
                end=fragment.locator.end,
                section=fragment.locator.section,
                path=fragment.locator.path,
            ),
            quote=source.quote,
            status=source.status,
            reason=source.reason,
        )

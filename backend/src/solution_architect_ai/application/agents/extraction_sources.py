from solution_architect_ai.application.context.context_models import ContextFragment, ContextPart
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    LocatorView,
    PartResult,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.domain.requirements import EvidenceStatus


def verify_evidence(evidence: Evidence, part: ContextPart) -> SourceRef:
    fragments: list[ContextFragment] = [
        item for item in part.fragments if str(item.fragment_id) == evidence.fragment_id
    ]
    if not fragments:
        return SourceRef(
            file_id=None,
            version_id=None,
            sha256=None,
            fragment_id=evidence.fragment_id,
            locator=None,
            quote=evidence.quote,
            status=EvidenceStatus.UNVERIFIED,
            reason="fragment_not_in_context",
        )
    matching: list[ContextFragment] = [
        item for item in fragments if evidence.quote.strip() and evidence.quote in item.text
    ]
    source: ContextFragment = matching[0] if matching else fragments[0]
    return SourceRef(
        file_id=source.file_id,
        version_id=source.version_id,
        sha256=source.sha256,
        fragment_id=evidence.fragment_id,
        locator=LocatorView(
            kind=source.locator.kind.value,
            start=source.locator.start,
            end=source.locator.end,
            section=source.locator.section,
            path=source.locator.path,
        ),
        quote=evidence.quote,
        status=EvidenceStatus.VERIFIED if matching else EvidenceStatus.UNVERIFIED,
        reason=None if matching else "quote_not_in_context",
    )


def reverify_part(result: PartResult, context: ContextPart) -> PartResult:
    updated: PartResult = result.model_copy(deep=True)
    requirement: RequirementView
    for requirement in updated.requirements:
        requirement.sources = [reverify_source(source, context) for source in requirement.sources]
        if not requirement.sources:
            requirement.sources = [
                SourceRef(
                    file_id=None,
                    version_id=None,
                    sha256=None,
                    fragment_id="",
                    locator=None,
                    quote="",
                    status=EvidenceStatus.UNVERIFIED,
                    reason="missing_evidence",
                )
            ]
    return updated


def reverify_source(source: SourceRef, context: ContextPart) -> SourceRef:
    if (
        not source.fragment_id
        or len(source.fragment_id) > 128
        or not source.quote.strip()
        or len(source.quote) > 8000
    ):
        return SourceRef(
            file_id=None,
            version_id=None,
            sha256=None,
            fragment_id=source.fragment_id,
            locator=None,
            quote=source.quote,
            status=EvidenceStatus.UNVERIFIED,
            reason="invalid_evidence",
        )
    return verify_evidence(Evidence(fragment_id=source.fragment_id, quote=source.quote), context)

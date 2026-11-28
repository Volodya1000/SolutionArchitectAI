from uuid import uuid4

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.context_models import ContextPart
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedContradiction,
    ExtractedGap,
    ExtractedRequirement,
    PartResult,
    RequirementsExtraction,
    RequirementView,
)
from solution_architect_ai.application.validation.source_language import validate_source_language
from solution_architect_ai.domain.requirements import RequirementCategory


def evidence_context(evidence: list[Evidence], part: ContextPart) -> str:
    texts: list[str] = []
    item: Evidence
    for item in evidence:
        identifier: str = part.resolve_source_label(item.fragment_id)
        fragments: list[str] = [
            fragment.text for fragment in part.fragments if str(fragment.fragment_id) == identifier
        ]
        if fragments:
            texts.append(
                item.quote if any(item.quote in text for text in fragments) else " ".join(fragments)
            )
    return " ".join(texts or [fragment.text for fragment in part.fragments])


def validate_context_language(result: RequirementsExtraction, part: ContextPart) -> None:
    requirement: ExtractedRequirement
    for requirement in result.requirements:
        source: str = evidence_context(requirement.evidence, part)
        validate_source_language(source, requirement.original_text)
        validate_source_language(source, requirement.normalized_text)
    issues: tuple[ExtractedGap | ExtractedContradiction, ...] = (
        *result.gaps,
        *result.contradictions,
    )
    issue: ExtractedGap | ExtractedContradiction
    for issue in issues:
        validate_source_language(evidence_context(issue.evidence, part), issue.description)


def requirement_view(candidate: ExtractedRequirement, part: ContextPart) -> RequirementView:
    return RequirementView(
        id=uuid4(),
        category=RequirementCategory(candidate.category),
        original_text=candidate.original_text,
        normalized_text=candidate.normalized_text,
        sources=[verify_evidence(evidence, part) for evidence in candidate.evidence],
    )


def issue_view(
    candidate: ExtractedGap | ExtractedContradiction, part: ContextPart
) -> RequirementView:
    category: RequirementCategory = (
        RequirementCategory.GAP
        if isinstance(candidate, ExtractedGap)
        else RequirementCategory.CONTRADICTION
    )
    return RequirementView(
        id=uuid4(),
        category=category,
        original_text="\n".join(evidence.quote for evidence in candidate.evidence),
        normalized_text=candidate.description,
        sources=[verify_evidence(evidence, part) for evidence in candidate.evidence],
    )


def verify_result(result: RequirementsExtraction, part: ContextPart) -> PartResult:
    requirements: list[RequirementView] = [
        requirement_view(item, part)
        for item in result.requirements
        if not all(
            part.resolve_source_label(evidence.fragment_id) in part.structural_fragment_ids
            for evidence in item.evidence
        )
    ]
    requirements.extend(issue_view(item, part) for item in result.gaps)
    requirements.extend(issue_view(item, part) for item in result.contradictions)
    return PartResult(
        part_id=part.id,
        requirements=requirements,
        fragment_ids=sorted(
            {
                str(item.fragment_id)
                for item in part.fragments
                if item.offset + len(item.text) >= item.total_length
            }
        ),
    )

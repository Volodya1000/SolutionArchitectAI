from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from solution_architect_ai.application.extraction_context import ContextPart
from solution_architect_ai.application.extraction_models import (
    ExtractedContradiction,
    ExtractedGap,
    ExtractedRequirement,
    PartResult,
    RequirementsExtraction,
    RequirementView,
)
from solution_architect_ai.application.extraction_prompt import CONTRACT_VERSION, PROMPT_VERSION
from solution_architect_ai.application.extraction_sources import verify_evidence
from solution_architect_ai.application.structured import StructuredOutputGenerator
from solution_architect_ai.application.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredRequest,
)
from solution_architect_ai.domain.requirements import RequirementCategory


@dataclass(frozen=True)
class AgentRequest:
    task_id: UUID
    run_id: UUID
    operation_id: UUID
    attempt_id: UUID
    part: ContextPart
    profile: ModelProfile
    contract_version: str = CONTRACT_VERSION
    prompt_version: str = PROMPT_VERSION
    role: Literal["requirements_extraction"] = "requirements_extraction"


@dataclass(frozen=True)
class AgentResult:
    run_id: UUID
    attempt_id: UUID
    payload: RequirementsExtraction
    contract_version: str = CONTRACT_VERSION
    role: Literal["requirements_extraction"] = "requirements_extraction"


class RequirementsExtractionAgent:
    def __init__(self, generator: StructuredOutputGenerator) -> None:
        self.generator: StructuredOutputGenerator = generator

    async def extract(self, request: AgentRequest, budget: ExecutionBudget) -> AgentResult:
        result: RequirementsExtraction = await self.generator.generate(
            StructuredRequest(request.part.messages, request.profile),
            RequirementsExtraction,
            budget,
        )
        return AgentResult(request.run_id, request.attempt_id, result)


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
        requirement_view(item, part) for item in result.requirements
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


def merge_parts(parts: list[PartResult]) -> list[RequirementView]:
    seen: set[str] = set()
    merged: list[RequirementView] = []
    for part in parts:
        for requirement in part.requirements:
            identity: str = requirement.model_dump_json(exclude={"id"})
            if identity not in seen:
                seen.add(identity)
                merged.append(requirement)
    return merged

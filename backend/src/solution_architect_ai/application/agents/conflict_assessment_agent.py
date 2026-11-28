from functools import partial

from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.conflict_agent_models import ConflictAssessmentPayload
from solution_architect_ai.application.models.conflict_assessment_models import (
    ConflictAssessmentVerdict,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredMessage,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.conflict_assessment_prompt import (
    CONFLICT_ASSESSMENT_PROMPT,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.clarification_validation import resolve_evidence
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import EvidenceStatus


def validate_conflict_assessment(
    verdict: ConflictAssessmentVerdict, context: ClarificationContext
) -> None:
    if any(
        verify_evidence(resolve_evidence(item, context), context.part).status
        != EvidenceStatus.VERIFIED
        for item in verdict.evidence
    ):
        raise ValueError("Conflict assessment evidence is not authentic to this source window")


class ConflictAssessmentAgent:
    def __init__(self, generator: StructuredOutputGenerator) -> None:
        self.generator: StructuredOutputGenerator = generator

    @staticmethod
    def request(requirement: RequirementView, context: ClarificationContext) -> StructuredRequest:
        payload: ConflictAssessmentPayload = ConflictAssessmentPayload(
            candidate_description=requirement.normalized_text,
            fragments=context.payload.fragments,
        )
        return StructuredRequest(
            (
                StructuredMessage(MessageRole.SYSTEM, CONFLICT_ASSESSMENT_PROMPT),
                StructuredMessage(MessageRole.USER, payload.model_dump_json()),
            ),
            context.profile,
        )

    async def assess(
        self, requirement: RequirementView, context: ClarificationContext, budget: ExecutionBudget
    ) -> ConflictAssessmentVerdict:
        return await self.generator.generate(
            self.request(requirement, context),
            ConflictAssessmentVerdict,
            budget,
            validator=partial(validate_conflict_assessment, context=context),
        )

from uuid import UUID

from solution_architect_ai.application.agents.conflict_assessment_agent import (
    ConflictAssessmentAgent,
    validate_conflict_assessment,
)
from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_question_merge import (
    merge_reasons,
    merge_sources,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
    ConflictAssessmentWindowResult,
)
from solution_architect_ai.application.models.conflict_assessment_models import (
    ConflictAssessment,
    ConflictAssessmentVerdict,
)
from solution_architect_ai.application.models.extraction_models import RequirementView, SourceRef
from solution_architect_ai.application.models.structured_models import ExecutionBudget
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.clarification_validation import resolve_evidence
from solution_architect_ai.application.workflows.clarification_review_cache import (
    ClarificationReviewCache,
)
from solution_architect_ai.application.workflows.clarification_review_progress import (
    ClarificationReviewProgress,
)
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory


class ClarificationConflictReview:
    def __init__(
        self, generator: StructuredOutputGenerator, cache: ClarificationReviewCache | None
    ) -> None:
        self.agent: ConflictAssessmentAgent = ConflictAssessmentAgent(generator)
        self.cache: ClarificationReviewCache | None = cache

    async def assess(
        self,
        requirement: RequirementView,
        windows: list[ClarificationContext],
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> ConflictAssessment:
        if not requirement.sources or any(
            source.status != EvidenceStatus.VERIFIED for source in requirement.sources
        ):
            return ConflictAssessment(
                requirement_id=requirement.id,
                status="candidate",
                reason="Источники кандидата не верифицированы",
                sources=requirement.sources,
            )
        verdicts: list[ConflictAssessmentVerdict] = []
        sources: list[SourceRef] = []
        context: ClarificationContext
        for context in windows:
            verdict: ConflictAssessmentVerdict = await self.window(
                requirement, context, budget, progress
            )
            verdicts.append(verdict)
            sources.extend(
                verify_evidence(resolve_evidence(item, context), context.part)
                for item in verdict.evidence
            )
        statuses: set[str] = {verdict.status for verdict in verdicts}
        return ConflictAssessment(
            requirement_id=requirement.id,
            status="confirmed"
            if "confirmed" in statuses and "refuted" not in statuses
            else "refuted"
            if "refuted" in statuses and "confirmed" not in statuses
            else "candidate",
            reason=merge_reasons([verdict.reason for verdict in verdicts]),
            sources=merge_sources(sources) or requirement.sources,
        )

    async def window(
        self,
        requirement: RequirementView,
        context: ClarificationContext,
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> ConflictAssessmentVerdict:
        budget.check()
        if self.cache is None:
            return await self.agent.assess(requirement, context, budget)
        key: str = self.cache.key(
            context,
            self.agent.request(requirement, context),
            ConflictAssessmentVerdict,
            requirement,
        )
        saved: ClarificationStepResult | None = await self.cache.load(key)
        if saved is None:
            before: int = budget.requests
            verdict: ConflictAssessmentVerdict = await self.agent.assess(
                requirement, context, budget
            )
            saved = await self.cache.save(
                key,
                ConflictAssessmentWindowResult(
                    verdict=verdict, model_requests=budget.requests - before
                ),
            )
        else:
            progress.restore_requests(saved.model_requests)
        if not isinstance(saved, ConflictAssessmentWindowResult):
            raise StoredExtractionCorrupt("stored_extraction_corrupt")
        validate_conflict_assessment(saved.verdict, context)
        return saved.verdict

    async def run(
        self,
        context: ClarificationContext,
        windows: list[ClarificationContext],
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> list[ConflictAssessment]:
        established: set[UUID] = {
            identifier
            for question in context.history
            if question.mandatory_conflict is not None
            for identifier in question.requirement_ids
        }
        return [
            await self.assess(requirement, windows, budget, progress)
            for requirement in context.requirements
            if requirement.category == RequirementCategory.CONTRADICTION
            and requirement.id not in established
        ]

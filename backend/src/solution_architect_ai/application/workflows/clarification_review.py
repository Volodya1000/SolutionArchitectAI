from collections.abc import Awaitable, Callable

from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.clarification_evidence_agent import (
    ClarificationEvidenceAgent,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.context.clarification_question_merge import (
    merge_question_windows,
)
from solution_architect_ai.application.context.mandatory_conflict_questions import (
    bind_confirmed_conflicts,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    ClarificationReviewCoverage,
)
from solution_architect_ai.application.models.clarification_review_models import (
    ClarificationReviewResult,
    SourceReviewVerdict,
)
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
    QuestionWindowResult,
    SourceReviewWindowResult,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredRequest,
)
from solution_architect_ai.application.validation.clarification_review_validation import (
    validate_source_review,
)
from solution_architect_ai.application.workflows.clarification_conflict_review import (
    ClarificationConflictReview,
)
from solution_architect_ai.application.workflows.clarification_review_cache import (
    ClarificationReviewCache,
    validate_cached_questions,
)
from solution_architect_ai.application.workflows.clarification_review_progress import (
    ClarificationReviewProgress,
)


class ClarificationReview:
    def __init__(
        self,
        clarification_agent: ClarificationAgent,
        review_cache: ClarificationReviewCache | None = None,
    ) -> None:
        self.clarification_agent: ClarificationAgent = clarification_agent
        self.clarification_evidence_agent: ClarificationEvidenceAgent = ClarificationEvidenceAgent(
            clarification_agent.structured_output_generator
        )
        self.review_cache: ClarificationReviewCache | None = review_cache

    async def run(
        self,
        original: ClarificationContext,
        budget: ExecutionBudget,
        on_progress: Callable[[ClarificationReviewCoverage], Awaitable[None]] | None = None,
        start_requests: int | None = None,
    ) -> ClarificationReviewResult:
        progress: ClarificationReviewProgress = ClarificationReviewProgress(
            original,
            budget.requests if start_requests is None else start_requests,
            on_progress,
            cumulative_usage=start_requests is not None,
        )
        await progress.publish(budget)
        try:
            return await self.review_context(original, budget, progress)
        except StructuredGenerationFailure:
            await progress.publish(budget)
            raise

    async def review_context(
        self,
        original: ClarificationContext,
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> ClarificationReviewResult:
        planner: ClarificationContextPlanner = ClarificationContextPlanner(
            self.clarification_agent.structured_output_generator, budget.correction_retries
        )
        windows: list[ClarificationContext] = await planner.plan(original)
        questions: list[ClarificationQuestion] = await self.collect_questions(
            windows, budget, progress
        )
        assessments: list[ConflictAssessment] = await ClarificationConflictReview(
            self.clarification_agent.structured_output_generator, self.review_cache
        ).run(original, windows, budget, progress)
        questions = bind_confirmed_conflicts(list(original.requirements), questions, assessments)
        retained: list[ClarificationQuestion] = []
        question: ClarificationQuestion
        for question in questions:
            if (
                question.status != "open"
                or question.mandatory_conflict is not None
                or not await self.has_resolving_evidence(question, windows, budget, progress)
            ):
                retained.append(question)
        await progress.publish(budget, complete=True)
        return ClarificationReviewResult(retained, progress.coverage, assessments)

    async def collect_questions(
        self,
        windows: list[ClarificationContext],
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> list[ClarificationQuestion]:
        questions: dict[str, list[ClarificationQuestion]] = {}
        index: int
        window: ClarificationContext
        question: ClarificationQuestion
        for index, window in enumerate(windows):
            for question in await self.questions_for_window(window, budget, progress):
                questions.setdefault(question.gap_key, []).append(question)
            progress.record(index, windows)
            await progress.publish(budget)
        return [merge_question_windows(questions[key]) for key in sorted(questions)]

    async def questions_for_window(
        self,
        context: ClarificationContext,
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> list[ClarificationQuestion]:
        budget.check()
        if self.review_cache is None:
            return await self.clarification_agent.clarify(context, budget)
        key: str = self.review_cache.key(
            context, StructuredRequest(context.part.messages, context.profile), ClarificationSet
        )
        saved: ClarificationStepResult | None = await self.review_cache.load(key)
        if saved is None:
            before: int = budget.requests
            questions: list[ClarificationQuestion] = await self.clarification_agent.clarify(
                context, budget
            )
            saved = await self.review_cache.save(
                key,
                QuestionWindowResult(
                    questions=questions,
                    model_requests=budget.requests - before,
                ),
            )
        else:
            progress.restore_requests(saved.model_requests)
        if not isinstance(saved, QuestionWindowResult):
            raise StoredExtractionCorrupt("stored_extraction_corrupt")
        validate_cached_questions(saved.questions, context)
        return saved.questions

    @staticmethod
    def unique_review_windows(windows: list[ClarificationContext]) -> list[ClarificationContext]:
        unique: dict[tuple[str, ...], ClarificationContext] = {}
        context: ClarificationContext
        for context in windows:
            identifiers: tuple[str, ...] = (
                tuple(
                    f"{fragment.fragment_id}:{fragment.offset}"
                    for fragment in context.part.fragments
                )
                + tuple(
                    f"{question.id}:{question.revision}" for question in context.payload.history
                )
                + tuple(
                    f"{decision.decision_id}:{decision.revision}"
                    for decision in context.payload.decisions
                )
            )
            unique.setdefault(identifiers, context)
        return list(unique.values())

    async def has_resolving_evidence(
        self,
        question: ClarificationQuestion,
        windows: list[ClarificationContext],
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress | None = None,
    ) -> bool:
        if not question.sources:
            return False
        unique: list[ClarificationContext] = sorted(
            self.unique_review_windows(windows),
            key=lambda context: not self.contains_question_source(question, context),
        )
        context: ClarificationContext
        for context in unique:
            verdict: SourceReviewVerdict = await self.review_evidence(
                question, context, budget, progress
            )
            if verdict.resolved:
                return True
        return False

    async def review_evidence(
        self,
        question: ClarificationQuestion,
        context: ClarificationContext,
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress | None,
    ) -> SourceReviewVerdict:
        budget.check()
        if self.review_cache is None:
            return await self.clarification_evidence_agent.review(question, context, budget)
        key: str = self.review_cache.key(
            context,
            self.clarification_evidence_agent.request(question, context),
            SourceReviewVerdict,
            question,
        )
        saved: ClarificationStepResult | None = await self.review_cache.load(key)
        if saved is None:
            before: int = budget.requests
            verdict: SourceReviewVerdict = await self.clarification_evidence_agent.review(
                question, context, budget
            )
            saved = await self.review_cache.save(
                key,
                SourceReviewWindowResult(
                    verdict=verdict,
                    model_requests=budget.requests - before,
                ),
            )
        elif progress is not None:
            progress.restore_requests(saved.model_requests)
        if not isinstance(saved, SourceReviewWindowResult):
            raise StoredExtractionCorrupt("stored_extraction_corrupt")
        validate_source_review(saved.verdict, context, question)
        return saved.verdict

    @staticmethod
    def contains_question_source(
        question: ClarificationQuestion, context: ClarificationContext
    ) -> bool:
        return any(
            source.quote in fragment.text and source.fragment_id == str(fragment.fragment_id)
            for source in question.sources
            for fragment in context.part.fragments
        )

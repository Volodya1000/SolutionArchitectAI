from collections.abc import Awaitable, Callable

from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.clarification_evidence_agent import (
    ClarificationEvidenceAgent,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
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
from solution_architect_ai.application.models.structured_models import ExecutionBudget
from solution_architect_ai.application.workflows.clarification_review_progress import (
    ClarificationReviewProgress,
)


class ClarificationReview:
    def __init__(self, clarification_agent: ClarificationAgent) -> None:
        self.clarification_agent: ClarificationAgent = clarification_agent
        self.clarification_evidence_agent: ClarificationEvidenceAgent = ClarificationEvidenceAgent(
            clarification_agent.structured_output_generator
        )

    async def run(
        self,
        original: ClarificationContext,
        budget: ExecutionBudget,
        on_progress: Callable[[ClarificationReviewCoverage], Awaitable[None]] | None = None,
    ) -> ClarificationReviewResult:
        progress: ClarificationReviewProgress = ClarificationReviewProgress(
            original, budget.requests, on_progress
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
        retained: list[ClarificationQuestion] = []
        question: ClarificationQuestion
        for question in questions:
            if (
                question.status != "open"
                or question.mandatory_conflict is not None
                or not await self.has_resolving_evidence(question, windows, budget)
            ):
                retained.append(question)
        await progress.publish(budget, complete=True)
        return ClarificationReviewResult(retained, progress.coverage)

    async def collect_questions(
        self,
        windows: list[ClarificationContext],
        budget: ExecutionBudget,
        progress: ClarificationReviewProgress,
    ) -> list[ClarificationQuestion]:
        questions: dict[str, ClarificationQuestion] = {}
        index: int
        window: ClarificationContext
        question: ClarificationQuestion
        for index, window in enumerate(windows):
            for question in await self.clarification_agent.clarify(window, budget):
                current: ClarificationQuestion | None = questions.get(question.gap_key)
                if current is None or question.status == "open":
                    questions[question.gap_key] = question
            progress.record(index, windows)
            await progress.publish(budget)
        return list(questions.values())

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
    ) -> bool:
        if not question.sources:
            return False
        unique: list[ClarificationContext] = sorted(
            self.unique_review_windows(windows),
            key=lambda context: not self.contains_question_source(question, context),
        )
        context: ClarificationContext
        for context in unique:
            verdict: SourceReviewVerdict = await self.clarification_evidence_agent.review(
                question, context, budget
            )
            if verdict.resolved:
                return True
        return False

    @staticmethod
    def contains_question_source(
        question: ClarificationQuestion, context: ClarificationContext
    ) -> bool:
        return any(
            source.quote in fragment.text and source.fragment_id == str(fragment.fragment_id)
            for source in question.sources
            for fragment in context.part.fragments
        )

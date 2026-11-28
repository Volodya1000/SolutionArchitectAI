from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.context_models import ContextFragment, ContextPack
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationReviewCoverage,
    ClarificationView,
    DecisionResult,
)
from solution_architect_ai.application.models.clarification_review_models import (
    ClarificationReviewResult,
)
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.models.structured_models import BudgetUsage, ExecutionBudget
from solution_architect_ai.application.prompts.clarification_prompt import PROMPT_VERSION
from solution_architect_ai.application.prompts.clarification_review_prompt import (
    PROMPT_VERSION as REVIEW_PROMPT_VERSION,
)
from solution_architect_ai.application.prompts.conflict_assessment_prompt import (
    CONFLICT_ASSESSMENT_PROMPT_VERSION,
)
from solution_architect_ai.application.protocols.clarification_protocols import ClarificationStore
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.workflows.clarification_review import ClarificationReview
from solution_architect_ai.application.workflows.clarification_review_cache import (
    ClarificationReviewCache,
)
from solution_architect_ai.application.workflows.extraction_budget_builder import (
    ExtractionBudgetBuilder,
)
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)


@dataclass
class ClarificationWorkflow:
    clarification_store_context: StoreContext[ClarificationStore]
    extraction_store_context: StoreContext[ExtractionStore]
    extraction_context_assembler: ExtractionContextAssembler
    extraction_budget_builder: ExtractionBudgetBuilder
    extraction_policy: ExtractionPolicy
    clarification_agent: ClarificationAgent
    documents_service: DocumentService

    async def get(self, run_id: UUID) -> ClarificationView:
        store: ClarificationStore
        async with self.clarification_store_context.open() as store:
            return await store.get(run_id)

    async def prepare_questions(self, run_id: UUID) -> None:
        view: ClarificationView = await self.get(run_id)
        if view.initialized:
            return
        context: ClarificationContext = await self.build_context(run_id, view)
        extraction_store: ExtractionStore
        async with self.extraction_store_context.open() as extraction_store:
            extraction: ExtractionView = await extraction_store.get(run_id)
            usage: BudgetUsage = await extraction_store.usage(run_id)
        budget: ExecutionBudget = self.extraction_budget_builder.build_budget(
            run_id, extraction, usage
        )
        metadata: ClarificationMetadata = ClarificationMetadata(
            prompt_version=PROMPT_VERSION,
            review_prompt_version=REVIEW_PROMPT_VERSION,
            context_digest=sha256(context.part.messages[-1].content.encode()).hexdigest(),
            model_profile=context.profile,
            review_start_requests=usage.requests,
            conflict_assessment_prompt_version=CONFLICT_ASSESSMENT_PROMPT_VERSION,
        )

        if (
            view.metadata is not None
            and view.metadata.review_start_requests is not None
            and (
                view.metadata.context_digest,
                view.metadata.model_profile,
                view.metadata.prompt_version,
                view.metadata.review_prompt_version,
                view.metadata.conflict_assessment_prompt_version,
            )
            == (
                metadata.context_digest,
                metadata.model_profile,
                metadata.prompt_version,
                metadata.review_prompt_version,
                metadata.conflict_assessment_prompt_version,
            )
        ):
            metadata.review_start_requests = view.metadata.review_start_requests

        async def record_progress(coverage: ClarificationReviewCoverage) -> None:
            metadata.coverage = coverage
            clarification_store: ClarificationStore
            async with self.clarification_store_context.open() as clarification_store:
                await clarification_store.set_review_metadata(run_id, metadata)

        result: ClarificationReviewResult = await ClarificationReview(
            self.clarification_agent,
            ClarificationReviewCache(run_id, self.clarification_store_context),
        ).run(context, budget, record_progress, metadata.review_start_requests)
        store: ClarificationStore
        async with self.clarification_store_context.open() as store:
            await store.save_conflict_assessments(run_id, result.assessments)
            await store.save_questions(run_id, result.questions, metadata)

    async def build_context(self, run_id: UUID, view: ClarificationView) -> ClarificationContext:
        store: ClarificationStore
        async with self.clarification_store_context.open() as store:
            history: list[ClarificationQuestion] = await store.history(run_id)
            decisions: list[DecisionResult] = await store.history_decisions(run_id)
        pack: ContextPack = await self.extraction_context_assembler.context(run_id)
        fragments: tuple[ContextFragment, ...] = tuple(
            fragment for part in pack.parts for fragment in part.fragments
        )
        return ClarificationContextBuilder().build_fragments(
            fragments,
            view.requirements,
            history,
            decisions,
            self.extraction_policy.profile,
        )

    async def waiting(self, run_id: UUID) -> None:
        store: ClarificationStore
        async with self.clarification_store_context.open() as store:
            await store.set_waiting(run_id)

    async def complete(self, run_id: UUID, expected_cycle: int) -> None:
        if (await self.get(run_id)).cycle != expected_cycle:
            return
        # Check immutable originals again after an arbitrarily long human pause.
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            versions: list[UUID] = (await store.command(run_id)).version_ids
        version_id: UUID
        for version_id in versions:
            await self.documents_service.read(version_id)
        clarification_store: ClarificationStore
        async with self.clarification_store_context.open() as clarification_store:
            await clarification_store.complete_cycle(run_id, expected_cycle)

    async def acknowledge(self, run_id: UUID, version: int) -> None:
        store: ClarificationStore
        async with self.clarification_store_context.open() as store:
            await store.acknowledge(run_id, version)

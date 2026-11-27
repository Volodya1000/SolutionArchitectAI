from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContext,
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.context_models import ContextFragment, ContextPack
from solution_architect_ai.application.models.clarification_models import (
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
)
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.models.structured_models import BudgetUsage, ExecutionBudget
from solution_architect_ai.application.prompts.clarification_prompt import PROMPT_VERSION
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStore,
    ClarificationStoreFactory,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.workflows.extraction_steps import ExtractionSteps


class ClarificationWorkflow:
    def __init__(
        self, stores: ClarificationStoreFactory, steps: ExtractionSteps, agent: ClarificationAgent
    ) -> None:
        self.stores: ClarificationStoreFactory = stores
        self.steps: ExtractionSteps = steps
        self.agent: ClarificationAgent = agent

    async def get(self, run_id: UUID) -> ClarificationView:
        store: ClarificationStore
        async with self.stores.open() as store:
            return await store.get(run_id)

    async def prepare_questions(self, run_id: UUID) -> None:
        view: ClarificationView = await self.get(run_id)
        if view.initialized:
            return
        store: ClarificationStore
        async with self.stores.open() as store:
            history: list[ClarificationQuestion] = await store.history(run_id)
            decisions: list[DecisionResult] = await store.history_decisions(run_id)
        pack: ContextPack = await self.steps.context(run_id)
        fragments: tuple[ContextFragment, ...] = tuple(
            fragment for part in pack.parts for fragment in part.fragments
        )
        context: ClarificationContext = ClarificationContextBuilder().build_fragments(
            fragments, view.requirements, history, decisions, self.steps.policy.profile
        )
        extraction_store: ExtractionStore
        async with self.steps.stores.open() as extraction_store:
            extraction: ExtractionView = await extraction_store.get(run_id)
            usage: BudgetUsage = await extraction_store.usage(run_id)
        budget: ExecutionBudget = self.steps.part_extractor.budget(run_id, extraction, usage)
        questions: list[ClarificationQuestion] = await self.agent.clarify(context, budget)
        async with self.stores.open() as store:
            await store.save_questions(
                run_id,
                questions,
                ClarificationMetadata(
                    prompt_version=PROMPT_VERSION,
                    context_digest=sha256(context.part.messages[-1].content.encode()).hexdigest(),
                    model_profile=context.profile,
                ),
            )

    async def waiting(self, run_id: UUID) -> None:
        store: ClarificationStore
        async with self.stores.open() as store:
            await store.set_waiting(run_id)

    async def complete(self, run_id: UUID, expected_cycle: int) -> None:
        if (await self.get(run_id)).cycle != expected_cycle:
            return
        # Check immutable originals again after an arbitrarily long human pause.
        store: ExtractionStore
        async with self.steps.stores.open() as store:
            versions: list[UUID] = (await store.command(run_id)).version_ids
        version_id: UUID
        for version_id in versions:
            await self.steps.documents.read(version_id)
        clarification_store: ClarificationStore
        async with self.stores.open() as clarification_store:
            await clarification_store.complete_cycle(run_id, expected_cycle)

    async def acknowledge(self, run_id: UUID, version: int) -> None:
        store: ClarificationStore
        async with self.stores.open() as store:
            await store.acknowledge(run_id, version)

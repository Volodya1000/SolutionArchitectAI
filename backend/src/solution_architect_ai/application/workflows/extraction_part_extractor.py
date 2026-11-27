from time import monotonic
from uuid import UUID, uuid4

from solution_architect_ai.application.agents.extraction_result_mapper import verify_result
from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.context.context_models import ContextPack
from solution_architect_ai.application.models.extraction_agent_models import (
    AgentRequest,
    AgentResult,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
    PartResult,
)
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.models.structured_models import (
    BudgetUsage,
    ExecutionBudget,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)


class ExtractionPartExtractor:
    def __init__(
        self,
        extraction_store_context: StoreContext[ExtractionStore],
        extraction_context_assembler: ExtractionContextAssembler,
        requirements_extraction_agent: RequirementsExtractionAgent,
        extraction_policy: ExtractionPolicy,
    ) -> None:
        self.extraction_store_context: StoreContext[ExtractionStore] = extraction_store_context
        self.extraction_context_assembler: ExtractionContextAssembler = extraction_context_assembler
        self.requirements_extraction_agent: RequirementsExtractionAgent = (
            requirements_extraction_agent
        )
        self.extraction_policy: ExtractionPolicy = extraction_policy

    async def reserve(self, run_id: UUID, previous: int, usage: BudgetUsage) -> None:
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            await store.reserve(run_id, usage, previous)

    async def extract(self, run_id: UUID, index: int) -> int:
        pack: ContextPack = await self.extraction_context_assembler.context(run_id)
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            existing: list[PartResult] = await store.parts(run_id)
            view: ExtractionView = await store.get(run_id)
            command: ExtractionStart = await store.command(run_id)
            usage: BudgetUsage = await store.usage(run_id)
        if index >= len(pack.parts):
            return len(pack.parts)
        part_id: str = pack.parts[index].id
        if part_id not in {part.part_id for part in existing}:
            budget: ExecutionBudget = self.budget(run_id, view, usage)
            request: AgentRequest = AgentRequest(
                self.extraction_policy.task_id,
                run_id,
                command.operation_id,
                uuid4(),
                pack.parts[index],
                self.extraction_policy.profile,
            )
            result: AgentResult = await self.requirements_extraction_agent.extract(request, budget)
            verified: PartResult = verify_result(result.payload, pack.parts[index])
            async with self.extraction_store_context.open() as store:
                await store.save_part(run_id, verified)
        return index + 1

    def budget(self, run_id: UUID, view: ExtractionView, usage: BudgetUsage) -> ExecutionBudget:
        elapsed: float = view.elapsed_seconds
        previous: int = usage.requests

        async def observe(updated: BudgetUsage) -> None:
            nonlocal previous
            await self.reserve(run_id, previous, updated)
            previous = updated.requests

        return ExecutionBudget(
            self.extraction_policy.requests,
            monotonic() + max(0, self.extraction_policy.deadline - elapsed),
            self.extraction_policy.request_timeout,
            self.extraction_policy.network_retries,
            self.extraction_policy.validation_retries,
            requests=usage.requests,
            network_failures=usage.network_failures,
            corrections=usage.corrections,
            on_usage=observe,
        )

    async def has_more(self, run_id: UUID, index: int) -> bool:
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            view: ExtractionView = await store.get(run_id)
        return index < view.progress.total_parts

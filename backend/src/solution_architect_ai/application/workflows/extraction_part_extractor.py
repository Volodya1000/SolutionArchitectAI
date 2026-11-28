from dataclasses import dataclass
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
from solution_architect_ai.application.workflows.extraction_budget_builder import (
    ExtractionBudgetBuilder,
)
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)


@dataclass
class ExtractionPartExtractor:
    extraction_store_context: StoreContext[ExtractionStore]
    extraction_context_assembler: ExtractionContextAssembler
    requirements_extraction_agent: RequirementsExtractionAgent
    extraction_policy: ExtractionPolicy
    extraction_budget_builder: ExtractionBudgetBuilder

    async def extract(self, run_id: UUID, index: int) -> int:
        pack: ContextPack = await self.extraction_context_assembler.context(run_id)
        if index >= len(pack.parts):
            return len(pack.parts)
        part_id: str = pack.parts[index].id
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            existing: PartResult | None = await store.get_part(run_id, part_id)
            if existing is not None:
                return index + 1
            view: ExtractionView = await store.get(run_id)
            command: ExtractionStart = await store.command(run_id)
            usage: BudgetUsage = await store.usage(run_id)
        budget: ExecutionBudget = self.extraction_budget_builder.build_budget(run_id, view, usage)
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

    async def has_more(self, run_id: UUID, index: int) -> bool:
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            view: ExtractionView = await store.get(run_id)
        return index < view.progress.total_parts

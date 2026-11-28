from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.models.structured_models import BudgetUsage, ExecutionBudget
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext


@dataclass
class ExtractionBudgetBuilder:
    extraction_store_context: StoreContext[ExtractionStore]
    extraction_policy: ExtractionPolicy

    async def reserve(self, run_id: UUID, previous: int, usage: BudgetUsage) -> None:
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            await store.reserve(run_id, usage, previous)

    def build_budget(
        self, run_id: UUID, view: ExtractionView, usage: BudgetUsage
    ) -> ExecutionBudget:
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

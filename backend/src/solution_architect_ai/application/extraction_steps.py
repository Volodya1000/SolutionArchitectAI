import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from solution_architect_ai.application.documents import DocumentService
from solution_architect_ai.application.errors import Conflict
from solution_architect_ai.application.extraction_agent import (
    AgentRequest,
    AgentResult,
    RequirementsExtractionAgent,
    merge_parts,
    verify_result,
)
from solution_architect_ai.application.extraction_context import (
    ContextBuilder,
    ContextPack,
    ContextPart,
)
from solution_architect_ai.application.extraction_models import (
    ExtractionStart,
    ExtractionView,
    PartResult,
)
from solution_architect_ai.application.extraction_ports import (
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.extraction_sources import reverify_part
from solution_architect_ai.application.structured_models import (
    BudgetUsage,
    ExecutionBudget,
    ModelProfile,
)
from solution_architect_ai.domain.documents import ParsedDocument


@dataclass(frozen=True)
class ExtractionPolicy:
    profile: ModelProfile
    config_digest: str
    task_id: UUID
    requests: int
    deadline: float
    request_timeout: float
    network_retries: int
    validation_retries: int


class ExtractionSteps:
    def __init__(
        self,
        stores: ExtractionStoreFactory,
        documents: DocumentService,
        builder: ContextBuilder,
        agent: RequirementsExtractionAgent,
        policy: ExtractionPolicy,
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.documents: DocumentService = documents
        self.builder: ContextBuilder = builder
        self.agent: RequirementsExtractionAgent = agent
        self.policy: ExtractionPolicy = policy

    async def context(self, run_id: UUID) -> ContextPack:
        store: ExtractionStore
        async with self.stores.open() as store:
            command: ExtractionStart = await store.command(run_id)
            if await store.config_digest(run_id) != self.policy.config_digest:
                raise Conflict("model_profile_changed")
        documents: tuple[ParsedDocument, ...] = tuple(
            [await self.documents.parsed(version) for version in command.version_ids]
        )
        return await asyncio.to_thread(self.builder.build, documents, command.analysis_scope)

    async def prepare(self, run_id: UUID) -> None:
        pack: ContextPack = await self.context(run_id)
        store: ExtractionStore
        async with self.stores.open() as store:
            await store.prepare(
                run_id, pack.digest, len(pack.parts), pack.total_fragments, pack.warnings
            )

    async def reserve(self, run_id: UUID, previous: int, usage: BudgetUsage) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            await store.reserve(run_id, usage, previous)

    async def extract(self, run_id: UUID, index: int) -> int:
        pack: ContextPack = await self.context(run_id)
        store: ExtractionStore
        async with self.stores.open() as store:
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
                self.policy.task_id,
                run_id,
                command.operation_id,
                uuid4(),
                pack.parts[index],
                self.policy.profile,
            )
            result: AgentResult = await self.agent.extract(request, budget)
            verified: PartResult = verify_result(result.payload, pack.parts[index])
            async with self.stores.open() as store:
                await store.save_part(run_id, verified)
        return index + 1

    def budget(self, run_id: UUID, view: ExtractionView, usage: BudgetUsage) -> ExecutionBudget:
        elapsed: float = (datetime.now(UTC) - view.created_at).total_seconds()
        previous: int = usage.requests

        async def observe(updated: BudgetUsage) -> None:
            nonlocal previous
            await self.reserve(run_id, previous, updated)
            previous = updated.requests

        return ExecutionBudget(
            self.policy.requests,
            monotonic() + max(0, self.policy.deadline - elapsed),
            self.policy.request_timeout,
            self.policy.network_retries,
            self.policy.validation_retries,
            requests=usage.requests,
            network_failures=usage.network_failures,
            corrections=usage.corrections,
            on_usage=observe,
        )

    async def has_more(self, run_id: UUID, index: int) -> bool:
        store: ExtractionStore
        async with self.stores.open() as store:
            view: ExtractionView = await store.get(run_id)
        return index < view.progress.total_parts

    async def merge(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            parts: list[PartResult] = await store.parts(run_id)
            view: ExtractionView = await store.get(run_id)
        if len(parts) != view.progress.total_parts:
            raise Conflict("incomplete_parts")
        merge_parts(parts)

    async def verify(self, run_id: UUID) -> None:
        pack: ContextPack = await self.context(run_id)
        store: ExtractionStore
        async with self.stores.open() as store:
            parts: list[PartResult] = await store.parts(run_id)
        if {part.part_id for part in parts} != {part.id for part in pack.parts}:
            raise Conflict("context_coverage_mismatch")
        contexts: dict[str, ContextPart] = {part.id: part for part in pack.parts}
        for part in parts:
            context: ContextPart = contexts[part.part_id]
            verified: PartResult = reverify_part(part, context)
            async with self.stores.open() as store:
                await store.reverify_part(run_id, verified)

    async def save(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            view: ExtractionView = await store.get(run_id)
            parts: list[PartResult] = await store.parts(run_id)
            elapsed: float = (datetime.now(UTC) - view.created_at).total_seconds()
            await store.complete(run_id, parts, elapsed)

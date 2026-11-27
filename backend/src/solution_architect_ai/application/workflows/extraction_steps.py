from uuid import UUID

from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.context.context_models import ContextPack
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStoreFactory,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)
from solution_architect_ai.application.workflows.extraction_finalizer import ExtractionFinalizer
from solution_architect_ai.application.workflows.extraction_part_extractor import (
    ExtractionPartExtractor,
)


class ExtractionSteps:
    """Expose the graph's checkpoint-compatible phases through focused collaborators."""

    def __init__(
        self,
        stores: ExtractionStoreFactory,
        documents: DocumentService,
        builder: ExtractionContextBuilder,
        requirements_extraction_agent: RequirementsExtractionAgent,
        policy: ExtractionPolicy,
    ) -> None:
        self.context_assembler: ExtractionContextAssembler = ExtractionContextAssembler(
            stores, documents, builder, policy
        )
        self.part_extractor: ExtractionPartExtractor = ExtractionPartExtractor(
            stores, self.context_assembler, requirements_extraction_agent, policy
        )
        self.finalizer: ExtractionFinalizer = ExtractionFinalizer(stores, self.context_assembler)

    @property
    def stores(self) -> ExtractionStoreFactory:
        return self.context_assembler.stores

    @property
    def documents(self) -> DocumentService:
        return self.context_assembler.documents

    @property
    def builder(self) -> ExtractionContextBuilder:
        return self.context_assembler.builder

    @property
    def requirements_extraction_agent(self) -> RequirementsExtractionAgent:
        return self.part_extractor.requirements_extraction_agent

    @property
    def policy(self) -> ExtractionPolicy:
        return self.context_assembler.policy

    @policy.setter
    def policy(self, policy: ExtractionPolicy) -> None:
        self.context_assembler.policy = policy
        self.part_extractor.policy = policy

    def release_context(self, run_id: UUID) -> None:
        self.context_assembler.release_context(run_id)

    async def context(self, run_id: UUID) -> ContextPack:
        return await self.context_assembler.context(run_id)

    async def prepare(self, run_id: UUID) -> None:
        await self.context_assembler.prepare(run_id)

    async def extract(self, run_id: UUID, index: int) -> int:
        return await self.part_extractor.extract(run_id, index)

    async def has_more(self, run_id: UUID, index: int) -> bool:
        return await self.part_extractor.has_more(run_id, index)

    async def validate_completed_parts(self, run_id: UUID) -> None:
        await self.finalizer.validate_completed_parts(run_id)

    async def verify(self, run_id: UUID) -> None:
        await self.finalizer.verify(run_id)

    async def save(self, run_id: UUID) -> None:
        await self.finalizer.save(run_id)

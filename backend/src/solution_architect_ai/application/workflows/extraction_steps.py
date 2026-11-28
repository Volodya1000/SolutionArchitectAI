from dataclasses import dataclass
from uuid import UUID

from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.context.context_models import ContextPack
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)
from solution_architect_ai.application.workflows.extraction_finalizer import ExtractionFinalizer
from solution_architect_ai.application.workflows.extraction_part_extractor import (
    ExtractionPartExtractor,
)


@dataclass
class ExtractionSteps:
    """Expose graph phases using collaborators assembled by dependency injection."""

    extraction_context_assembler: ExtractionContextAssembler
    extraction_part_extractor: ExtractionPartExtractor
    extraction_finalizer: ExtractionFinalizer

    @property
    def extraction_store_context(self) -> StoreContext[ExtractionStore]:
        return self.extraction_context_assembler.extraction_store_context

    @property
    def documents_service(self) -> DocumentService:
        return self.extraction_context_assembler.documents_service

    @property
    def extraction_context_builder(self) -> ExtractionContextBuilder:
        return self.extraction_context_assembler.extraction_context_builder

    @property
    def requirements_extraction_agent(self) -> RequirementsExtractionAgent:
        return self.extraction_part_extractor.requirements_extraction_agent

    @property
    def extraction_policy(self) -> ExtractionPolicy:
        return self.extraction_context_assembler.extraction_policy

    def release_context(self, run_id: UUID) -> None:
        self.extraction_context_assembler.release_context(run_id)

    async def context(self, run_id: UUID) -> ContextPack:
        return await self.extraction_context_assembler.context(run_id)

    async def prepare(self, run_id: UUID) -> None:
        await self.extraction_context_assembler.prepare(run_id)

    async def extract(self, run_id: UUID, index: int) -> int:
        return await self.extraction_part_extractor.extract(run_id, index)

    async def has_more(self, run_id: UUID, index: int) -> bool:
        return await self.extraction_part_extractor.has_more(run_id, index)

    async def validate_completed_parts(self, run_id: UUID) -> None:
        await self.extraction_finalizer.validate_completed_parts(run_id)

    async def verify(self, run_id: UUID) -> None:
        await self.extraction_finalizer.verify(run_id)

    async def save(self, run_id: UUID) -> None:
        await self.extraction_finalizer.save(run_id)

    async def save_candidates(self, run_id: UUID) -> None:
        await self.extraction_finalizer.save(run_id, defer_completion=True)

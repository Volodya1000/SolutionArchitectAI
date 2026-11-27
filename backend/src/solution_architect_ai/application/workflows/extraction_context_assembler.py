import asyncio
from uuid import UUID

from solution_architect_ai.application.context.context_models import (
    ContextPack,
    ContextPolicy,
)
from solution_architect_ai.application.context.extraction_context_builder import (
    ExtractionContextBuilder,
)
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
)
from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.domain.documents import ParsedDocument


class ExtractionContextAssembler:
    def __init__(
        self,
        extraction_store_context: StoreContext[ExtractionStore],
        documents_service: DocumentService,
        extraction_context_builder: ExtractionContextBuilder,
        extraction_policy: ExtractionPolicy,
    ) -> None:
        self.extraction_store_context: StoreContext[ExtractionStore] = extraction_store_context
        self.documents_service: DocumentService = documents_service
        self.extraction_context_builder: ExtractionContextBuilder = extraction_context_builder
        self.extraction_policy: ExtractionPolicy = extraction_policy
        self.contexts: dict[UUID, tuple[tuple[str, str, ContextPolicy], ContextPack]] = {}

    def release_context(self, run_id: UUID) -> None:
        self.contexts.pop(run_id, None)

    async def context(self, run_id: UUID) -> ContextPack:
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            command: ExtractionStart = await store.command(run_id)
            expected_context: str | None = await store.context_digest(run_id)
            if await store.config_digest(run_id) != self.extraction_policy.config_digest:
                raise Conflict("model_profile_changed")
        signature: tuple[str, str, ContextPolicy] = (
            self.extraction_policy.config_digest,
            self.extraction_context_builder.schema,
            self.extraction_context_builder.context_policy,
        )
        cached: tuple[tuple[str, str, ContextPolicy], ContextPack] | None = self.contexts.get(
            run_id
        )
        if cached is not None and cached[0] == signature:
            self.validate_context_digest(cached[1], expected_context)
            return cached[1]
        parsed_documents: tuple[ParsedDocument, ...] = tuple(
            [
                await self.documents_service.get_parsed_document(version)
                for version in command.version_ids
            ]
        )
        pack: ContextPack = await asyncio.to_thread(
            self.extraction_context_builder.build, parsed_documents, command.analysis_scope
        )
        self.validate_context_digest(pack, expected_context)
        self.contexts[run_id] = (signature, pack)
        return pack

    @staticmethod
    def validate_context_digest(pack: ContextPack, expected_context: str | None) -> None:
        if expected_context is not None and expected_context != pack.digest:
            raise Conflict("context_changed")

    async def prepare(self, run_id: UUID) -> None:
        pack: ContextPack = await self.context(run_id)
        if len(pack.parts) > self.extraction_policy.requests:
            raise StructuredGenerationFailure(StructuredErrorCode.BUDGET_EXHAUSTED)
        store: ExtractionStore
        async with self.extraction_store_context.open() as store:
            await store.prepare(
                run_id, pack.digest, len(pack.parts), pack.total_fragments, pack.warnings
            )

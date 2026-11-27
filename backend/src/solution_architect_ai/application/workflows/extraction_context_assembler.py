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
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.domain.documents import ParsedDocument


class ExtractionContextAssembler:
    def __init__(
        self,
        stores: ExtractionStoreFactory,
        documents: DocumentService,
        builder: ExtractionContextBuilder,
        policy: ExtractionPolicy,
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.documents: DocumentService = documents
        self.builder: ExtractionContextBuilder = builder
        self.policy: ExtractionPolicy = policy
        self.contexts: dict[UUID, tuple[tuple[str, str, ContextPolicy], ContextPack]] = {}

    def release_context(self, run_id: UUID) -> None:
        self.contexts.pop(run_id, None)

    async def context(self, run_id: UUID) -> ContextPack:
        store: ExtractionStore
        async with self.stores.open() as store:
            command: ExtractionStart = await store.command(run_id)
            expected_context: str | None = await store.context_digest(run_id)
            if await store.config_digest(run_id) != self.policy.config_digest:
                raise Conflict("model_profile_changed")
        signature: tuple[str, str, ContextPolicy] = (
            self.policy.config_digest,
            self.builder.schema,
            self.builder.policy,
        )
        cached: tuple[tuple[str, str, ContextPolicy], ContextPack] | None = self.contexts.get(
            run_id
        )
        if cached is not None and cached[0] == signature:
            self.validate_context_digest(cached[1], expected_context)
            return cached[1]
        documents: tuple[ParsedDocument, ...] = tuple(
            [await self.documents.get_parsed_document(version) for version in command.version_ids]
        )
        pack: ContextPack = await asyncio.to_thread(
            self.builder.build, documents, command.analysis_scope
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
        if len(pack.parts) > self.policy.requests:
            raise StructuredGenerationFailure(StructuredErrorCode.BUDGET_EXHAUSTED)
        store: ExtractionStore
        async with self.stores.open() as store:
            await store.prepare(
                run_id, pack.digest, len(pack.parts), pack.total_fragments, pack.warnings
            )

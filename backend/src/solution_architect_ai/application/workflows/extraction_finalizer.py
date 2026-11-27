from uuid import UUID

from solution_architect_ai.application.agents.extraction_sources import reverify_part
from solution_architect_ai.application.context.context_models import ContextPack, ContextPart
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
    PartResult,
)
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)


class ExtractionFinalizer:
    def __init__(
        self, stores: ExtractionStoreFactory, context_assembler: ExtractionContextAssembler
    ) -> None:
        self.stores: ExtractionStoreFactory = stores
        self.context_assembler: ExtractionContextAssembler = context_assembler

    async def validate_completed_parts(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            parts: list[PartResult] = await store.parts(run_id)
            view: ExtractionView = await store.get(run_id)
        if len(parts) != view.progress.total_parts:
            raise Conflict("incomplete_parts")
        # Merging is materialized atomically by store.complete after source verification.

    async def verify(self, run_id: UUID) -> None:
        pack: ContextPack = await self.context_assembler.context(run_id)
        store: ExtractionStore
        async with self.stores.open() as store:
            parts: list[PartResult] = await store.parts(run_id)
            command: ExtractionStart = await store.command(run_id)
        # Reuse the built context, but verify that its originals still exist and
        # match their hashes before publishing verified sources or resuming SAVE.
        version_id: UUID
        for version_id in command.version_ids:
            await self.context_assembler.documents.read(version_id)
        if {part.part_id for part in parts} != {part.id for part in pack.parts}:
            raise Conflict("context_coverage_mismatch")
        contexts: dict[str, ContextPart] = {part.id: part for part in pack.parts}
        part: PartResult
        for part in parts:
            context: ContextPart = contexts[part.part_id]
            verified: PartResult = reverify_part(part, context)
            async with self.stores.open() as store:
                await store.reverify_part(run_id, verified)

    async def save(self, run_id: UUID, *, defer_completion: bool = False) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            if (await store.get(run_id)).status.terminal:
                return
        await self.verify(run_id)
        async with self.stores.open() as store:
            view: ExtractionView = await store.get(run_id)
            parts: list[PartResult] = await store.parts(run_id)
            await store.complete(run_id, parts, view.elapsed_seconds, finalize=not defer_completion)

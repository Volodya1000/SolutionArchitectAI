from uuid import UUID

from pydantic import TypeAdapter

from solution_architect_ai.application.errors.clarification_errors import ClarificationConflict
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationView,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
    SourceVersion,
)
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStore,
    ClarificationStoreFactory,
)
from solution_architect_ai.application.services.document_service import DocumentService


class ClarificationService:
    def __init__(self, stores: ClarificationStoreFactory, documents: DocumentService) -> None:
        self.stores: ClarificationStoreFactory = stores
        self.documents: DocumentService = documents

    async def get(self, run_id: UUID) -> ClarificationView:
        store: ClarificationStore
        async with self.stores.open() as store:
            return await store.get(run_id)

    async def answer(
        self, run_id: UUID, question_id: UUID, command: AnswerClarification
    ) -> DecisionResult:
        # Access and optimistic versions are checked again under the question-row lock.
        store: ClarificationStore
        async with self.stores.open() as store:
            cached: DecisionResult | None = await store.preflight_answer(
                run_id, question_id, command
            )
        if cached is not None:
            return cached
        await self.verify_versions(command.source_versions)
        async with self.stores.open() as store:
            return await store.answer(run_id, question_id, command)

    async def resolve(self, decision_id: UUID, command: ResolveAssumption) -> DecisionResult:
        store: ClarificationStore
        async with self.stores.open() as store:
            return await store.resolve(decision_id, command)

    async def resume(self, run_id: UUID, command: ResumeRun) -> CommandResult:
        store: ClarificationStore
        async with self.stores.open() as store:
            cached: CommandResult | None = await store.preflight_resume(run_id, command)
        if cached is not None:
            return cached
        await self.verify_versions(command.source_versions)
        async with self.stores.open() as store:
            return await store.resume(run_id, command)

    async def verify_versions(self, sources: list[SourceVersion]) -> None:
        source: SourceVersion
        for source in sources:
            if (await self.documents.get_version(source.version_id)).sha256 != source.sha256:
                raise ClarificationConflict("source_versions_changed")
            await self.documents.read(source.version_id)

    async def operation(self, operation_id: UUID) -> DecisionResult | CommandResult:
        store: ClarificationStore
        async with self.stores.open() as store:
            payload: str = await store.operation(operation_id)
        return TypeAdapter(DecisionResult | CommandResult).validate_json(payload)

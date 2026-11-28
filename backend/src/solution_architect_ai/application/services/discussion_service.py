from uuid import UUID, uuid4

from solution_architect_ai.application.context.discussion_scope import select_discussion_scope
from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.models.chat_dto import ChatView
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.discussion_models import (
    CreateDiscussion,
    DiscussionBinding,
    DiscussionView,
    RequirementSubject,
    SourceSubject,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
    LocatorView,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.protocols.discussion_protocols import DiscussionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument
from solution_architect_ai.domain.requirements import EvidenceStatus


class DiscussionService:
    def __init__(
        self,
        discussion_store_context: StoreContext[DiscussionStore],
        documents_service: DocumentService,
        clarification_service: ClarificationService,
    ) -> None:
        self.discussion_store_context: StoreContext[DiscussionStore] = discussion_store_context
        self.documents_service: DocumentService = documents_service
        self.clarification_service: ClarificationService = clarification_service

    async def create(self, command: CreateDiscussion) -> ChatView:
        store: DiscussionStore
        async with self.discussion_store_context.open() as store:
            replay: ChatView | None = await store.replay(command)
        if replay is not None:
            return replay
        binding: DiscussionBinding = (
            await self.requirement_binding(command.subject)
            if isinstance(command.subject, RequirementSubject)
            else await self.source_binding(command.subject)
        )
        async with self.discussion_store_context.open() as store:
            return await store.create(command, binding)

    async def source_reference(self, version_id: UUID, fragment_id: UUID) -> SourceRef:
        store: DiscussionStore
        async with self.discussion_store_context.open() as store:
            await store.check_version(version_id)
        document: ParsedDocument = await self.documents_service.get_parsed_document(version_id)
        fragment: DocumentFragment | None = next(
            (item for item in document.fragments if item.fragment_id == fragment_id), None
        )
        if fragment is None:
            raise Missing("source_fragment")
        return SourceRef(
            file_id=document.file_id,
            version_id=document.version_id,
            sha256=document.sha256,
            fragment_id=str(fragment.fragment_id),
            locator=LocatorView(
                kind=fragment.locator.kind.value,
                start=fragment.locator.start,
                end=fragment.locator.end,
                section=fragment.locator.section,
                path=fragment.locator.path,
            ),
            quote=fragment.text,
            status=EvidenceStatus.VERIFIED,
            reason=None,
        )

    async def requirement_binding(self, subject: RequirementSubject) -> DiscussionBinding:
        store: DiscussionStore
        async with self.discussion_store_context.open() as store:
            analysis: ExtractionView = await store.analysis(subject.run_id)
        requirement: RequirementView | None = next(
            (item for item in analysis.requirements if item.id == subject.requirement_id), None
        )
        if requirement is None:
            raise Missing("requirement")
        # Resolve the version/fragment pair on the server; never accept caller-supplied locators.
        sources: list[SourceRef] = []
        source: SourceRef
        for source in requirement.sources:
            if source.version_id is None or source.version_id not in analysis.version_ids:
                raise Missing("requirement_source")
            sources.append(await self.source_reference(source.version_id, UUID(source.fragment_id)))
        if not sources:
            raise Missing("requirement_source")
        state: ClarificationView = await self.clarification_service.get(subject.run_id)
        return DiscussionBinding(
            view=DiscussionView(
                chat_id=uuid4(),
                kind="requirement",
                title=requirement.normalized_text,
                analysis_id=subject.run_id,
                requirement_id=subject.requirement_id,
                version_id=sources[0].version_id,
                fragment_id=UUID(sources[0].fragment_id),
                version_ids=list(
                    dict.fromkeys(
                        source.version_id for source in sources if source.version_id is not None
                    )
                ),
                history_id=state.history_id,
                backlink=f"/requirements?run={subject.run_id}&requirement={subject.requirement_id}",
            ),
            sources=sources,
            candidate_sources=requirement.sources,
        )

    async def source_binding(self, subject: SourceSubject) -> DiscussionBinding:
        source: SourceRef = await self.source_reference(subject.version_id, subject.fragment_id)
        history_id: UUID | None = None
        if subject.analysis_id is not None:
            store: DiscussionStore
            async with self.discussion_store_context.open() as store:
                analysis: ExtractionView = await store.analysis(subject.analysis_id)
            if subject.version_id not in analysis.version_ids:
                raise Missing("analysis_source_version")
            state: ClarificationView = await self.clarification_service.get(subject.analysis_id)
            history_id = state.history_id
        analysis_query: str = (
            f"&run={subject.analysis_id}" if subject.analysis_id is not None else ""
        )
        return DiscussionBinding(
            view=DiscussionView(
                chat_id=uuid4(),
                kind="source",
                title=source.quote,
                analysis_id=subject.analysis_id,
                requirement_id=None,
                version_id=subject.version_id,
                fragment_id=subject.fragment_id,
                version_ids=[subject.version_id],
                history_id=history_id,
                backlink=f"/documents?version={subject.version_id}&fragment={subject.fragment_id}"
                + analysis_query,
            ),
            sources=[source],
        )

    async def get_binding(self, chat_id: UUID) -> DiscussionBinding | None:
        store: DiscussionStore
        async with self.discussion_store_context.open() as store:
            return await store.get(chat_id)

    async def get(self, chat_id: UUID) -> DiscussionView | None:
        binding: DiscussionBinding | None = await self.get_binding(chat_id)
        return None if binding is None else binding.view

    async def operation(self, operation_id: UUID) -> ChatView:
        store: DiscussionStore
        async with self.discussion_store_context.open() as store:
            return await store.operation(operation_id)

    async def get_clarifications(self, chat_id: UUID) -> ClarificationView | None:
        binding: DiscussionBinding | None = await self.get_binding(chat_id)
        return None if binding is None else await self.clarification_scope(binding)

    async def clarification_scope(self, binding: DiscussionBinding) -> ClarificationView | None:
        if binding.view.analysis_id is None:
            return None
        state: ClarificationView = await self.clarification_service.get(binding.view.analysis_id)
        return select_discussion_scope(binding, state)

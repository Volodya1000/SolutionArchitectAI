from uuid import UUID

from solution_architect_ai.application.context.discussion_sources import (
    DiscussionSourceContextBuilder,
)
from solution_architect_ai.application.errors.chat_errors import GenerationFailure, Missing
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.discussion_context_models import (
    DiscussionAnalysisContext,
    DiscussionContextManifest,
    DiscussionModelContext,
)
from solution_architect_ai.application.models.discussion_models import DiscussionBinding
from solution_architect_ai.application.models.extraction_models import SourceRef
from solution_architect_ai.application.prompts.discussion_prompt import (
    OMISSION_REASON,
    discussion_messages,
)
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.domain.runs import RunErrorCode


def analysis_context(state: ClarificationView | None) -> DiscussionAnalysisContext | None:
    if state is None:
        return None
    return DiscussionAnalysisContext(
        run_id=state.run_id,
        history_id=state.history_id,
        cycle=state.cycle,
        initialized=state.initialized,
        resume_pending=state.resume_pending,
        resume_version=state.resume_version,
        requirements=state.requirements,
        questions=state.questions,
        decisions=state.decisions,
        risks=state.risks,
    )


class DiscussionContextBuilder:
    def __init__(self, discussion_service: DiscussionService) -> None:
        self.discussion_service: DiscussionService = discussion_service
        self.source_context_builder: DiscussionSourceContextBuilder = (
            DiscussionSourceContextBuilder(discussion_service)
        )

    async def messages(self, chat_id: UUID) -> list[MessageView]:
        binding: DiscussionBinding | None = await self.discussion_service.get_binding(chat_id)
        if binding is None:
            return []
        sources: list[SourceRef]
        omitted_fragments: int
        try:
            sources, omitted_fragments = await self.source_context_builder.sources(binding)
        except (DocumentFailure, Missing, ValueError) as error:
            raise GenerationFailure(RunErrorCode.DISCUSSION_SOURCE_UNAVAILABLE) from error
        try:
            state: ClarificationView | None = await self.discussion_service.clarification_scope(
                binding
            )
        except Missing as error:
            raise GenerationFailure(RunErrorCode.DISCUSSION_SUBJECT_UNAVAILABLE) from error
        context: DiscussionModelContext = DiscussionModelContext(
            subject=binding.view,
            candidate_sources=binding.candidate_sources,
            source_fragments=sources,
            context_manifest=DiscussionContextManifest(
                included_fragment_ids=[source.fragment_id for source in sources],
                omitted_fragment_count=omitted_fragments,
                omission_reason=OMISSION_REASON,
            ),
            analysis=analysis_context(state),
        )
        return discussion_messages(context)

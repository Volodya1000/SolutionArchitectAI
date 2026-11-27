from uuid import UUID

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    DecisionResult,
    RiskView,
)
from solution_architect_ai.application.models.discussion_models import DiscussionView
from solution_architect_ai.application.models.extraction_models import RequirementView, SourceRef


class DiscussionContextManifest(DTO):
    included_fragment_ids: list[str]
    omitted_fragment_count: int
    omission_reason: str


class DiscussionAnalysisContext(DTO):
    run_id: UUID
    history_id: UUID
    cycle: int
    initialized: bool
    resume_pending: bool
    resume_version: int
    requirements: list[RequirementView]
    questions: list[ClarificationQuestion]
    decisions: list[DecisionResult]
    risks: list[RiskView]


class DiscussionModelContext(DTO):
    subject: DiscussionView
    candidate_sources: list[SourceRef]
    source_fragments: list[SourceRef]
    context_manifest: DiscussionContextManifest
    analysis: DiscussionAnalysisContext | None

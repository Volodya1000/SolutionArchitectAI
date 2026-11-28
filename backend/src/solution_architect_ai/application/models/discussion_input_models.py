from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from solution_architect_ai.application.models.chat_dto import DTO, MessageView
from solution_architect_ai.application.models.clarification_models import (
    AssumptionDetails,
    QuestionStatus,
)
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory


class DiscussionInputEvidence(DTO):
    fragment_id: str
    quote: str
    status: EvidenceStatus
    reason: str | None


class DiscussionInputSource(DiscussionInputEvidence):
    location: str


class DiscussionInputRequirement(DTO):
    id: str
    category: RequirementCategory
    original_text: str
    normalized_text: str
    sources: list[DiscussionInputEvidence]


class DiscussionInputQuestion(DTO):
    id: str
    revision: int
    text: str
    basis: str
    dependent_decision: str
    blocking: bool
    status: QuestionStatus
    mandatory_conflict: str | None
    requirement_ids: list[str]
    sources: list[DiscussionInputEvidence]


class DiscussionInputDecision(DTO):
    id: str
    revision: int
    question_id: str
    question_revision: int
    applies_to_current_question: bool
    analysis: str
    requirement_ids: list[str]
    kind: Literal["answer", "assumption"]
    text: str
    basis: str
    author: str
    created_at: datetime
    assumption: AssumptionDetails | None
    resolution: Literal["pending", "confirmed", "rejected"]
    resolution_reason: str | None


class DiscussionInputRisk(DTO):
    id: str
    decision_id: str
    consequences: str
    mitigation: str
    status: Literal["open", "closed", "realized"]
    resolution_reason: str | None


class DiscussionInputAnalysis(DTO):
    id: str
    requirements: list[DiscussionInputRequirement]
    questions: list[DiscussionInputQuestion]
    decisions: list[DiscussionInputDecision]
    risks: list[DiscussionInputRisk]


class DiscussionInputSubject(DTO):
    kind: Literal["requirement", "source"]
    title: str
    requirement_id: str | None
    fragment_id: str | None


class DiscussionInput(DTO):
    subject: DiscussionInputSubject
    candidate_sources: list[DiscussionInputEvidence]
    source_fragments: list[DiscussionInputSource]
    analysis: DiscussionInputAnalysis | None
    omitted_fragment_count: int
    omission_reason: str


@dataclass(frozen=True)
class PreparedDiscussion:
    messages: list[MessageView]
    references: Mapping[str, str]

    def model_history(self, history: list[MessageView]) -> list[MessageView]:
        result: list[MessageView] = []
        message: MessageView
        for message in history:
            content: str = message.content
            label: str
            target: str
            for label, target in sorted(self.references.items(), key=lambda item: -len(item[1])):
                content = content.replace(target, f"ref:{label}")
            result.append(message.model_copy(update={"content": content}))
        return result

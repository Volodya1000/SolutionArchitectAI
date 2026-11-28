from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from solution_architect_ai.application.models.chat_dto import DTO, Text
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import RequirementView, SourceRef
from solution_architect_ai.application.models.structured_models import ModelProfile

type QuestionStatus = Literal["open", "answered", "assumed"]


@dataclass(frozen=True)
class ActorContext:
    id: UUID
    name: str
    task_id: UUID
    can_write: bool = True

    @classmethod
    def local(cls, task_id: UUID) -> ActorContext:
        return cls(UUID("10000000-0000-4000-8000-000000000003"), "Локальный архитектор", task_id)


class SourceVersion(DTO):
    version_id: UUID
    sha256: Annotated[str, StringConstraints(pattern="^[0-9a-f]{64}$")]


def normalize_versions(sources: list[SourceVersion]) -> list[SourceVersion]:
    if len({source.version_id for source in sources}) != len(sources):
        raise ValueError("Duplicate source versions")
    return sorted(sources, key=lambda source: str(source.version_id))


class AssumptionDetails(DTO):
    responsible: Text
    verification_condition: Text
    consequences: Text
    mitigation: Text


class ClarificationQuestion(DTO):
    id: UUID
    gap_key: Text
    revision: int = 1
    text: Text
    basis: Text
    dependent_decision: Text
    blocking: bool
    requirement_ids: Annotated[list[UUID], Field(min_length=1)]
    sources: list[SourceRef]
    status: QuestionStatus = "open"
    previous_basis: str | None = None
    previous_sources: list[SourceRef] = Field(default_factory=list)
    mandatory_conflict: str | None = None
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    requirement_fingerprints: dict[UUID, str] = Field(default_factory=dict)
    requirement_basis_fingerprints: dict[UUID, str] = Field(default_factory=dict)

    @property
    def blocks_completion(self) -> bool:
        return (self.blocking and self.status == "open") or (
            self.status in {"open", "assumed"} and self.mandatory_conflict is not None
        )


class AnswerClarification(DTO):
    operation_id: UUID
    expected_question_revision: Annotated[int, Field(ge=1)]
    source_versions: Annotated[list[SourceVersion], Field(max_length=20)]
    kind: Literal["answer", "assumption"]
    text: Text
    basis: Text
    assumption: AssumptionDetails | None = None

    @model_validator(mode="after")
    def validate_assumption(self) -> AnswerClarification:
        self.source_versions = normalize_versions(self.source_versions)
        if (self.kind == "assumption") != (self.assumption is not None):
            raise ValueError("Assumption details are required only for an assumption")
        return self


class ResumeRun(DTO):
    operation_id: UUID
    question_revisions: dict[UUID, int]
    source_versions: Annotated[list[SourceVersion], Field(max_length=20)]

    @model_validator(mode="after")
    def validate_versions(self) -> ResumeRun:
        self.source_versions = normalize_versions(self.source_versions)
        return self


class ResolveAssumption(DTO):
    operation_id: UUID
    expected_revision: Annotated[int, Field(ge=1)]
    resolution: Literal["confirm", "reject"]
    reason: Text


class DecisionResult(DTO):
    operation_id: UUID
    run_id: UUID
    question_id: UUID
    question_revision: int
    decision_id: UUID
    kind: Literal["answer", "assumption"]
    text: str
    basis: str
    author_id: UUID
    author: str
    created_at: datetime
    requirement_ids: list[UUID]
    source_versions: list[SourceVersion] = Field(default_factory=list)
    assumption: AssumptionDetails | None = None
    risk_id: UUID | None = None
    resolution: Literal["pending", "confirmed", "rejected"] = "pending"
    resolution_reason: str | None = None
    revision: int = 1
    resolved_by: UUID | None = None
    resolved_author: str | None = None
    resolved_at: datetime | None = None


class RiskView(DTO):
    id: UUID
    decision_id: UUID
    consequences: str
    mitigation: str
    status: Literal["open", "closed", "realized"] = "open"
    resolution_reason: str | None = None


class CompletedCycle(DTO):
    cycle: int
    completed_at: datetime
    decision_ids: list[UUID]
    requirements: list[RequirementView] = Field(default_factory=list)


class ClarificationReviewCoverage(DTO):
    total_fragments: int = 0
    reviewed_fragments: int = 0
    total_history: int = 0
    reviewed_history: int = 0
    model_requests: int = 0
    complete: bool = False
    unreviewed_fragment_ids: list[str] = Field(default_factory=list)
    unreviewed_question_ids: list[UUID] = Field(default_factory=list)


class ClarificationMetadata(DTO):
    prompt_version: str
    review_prompt_version: str | None = None
    contract_version: str = "clarification-1"
    context_digest: str
    model_profile: ModelProfile
    coverage: ClarificationReviewCoverage | None = None
    review_start_requests: int | None = Field(default=None, ge=0)
    conflict_assessment_prompt_version: str | None = None


class ClarificationView(DTO):
    run_id: UUID
    history_id: UUID
    cycle: int = 0
    initialized: bool = False
    resume_pending: bool = False
    resume_version: int = 0
    metadata: ClarificationMetadata | None = None
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    decisions: list[DecisionResult] = Field(default_factory=list)
    risks: list[RiskView] = Field(default_factory=list)
    requirements: list[RequirementView] = Field(default_factory=list)
    completed_cycles: list[CompletedCycle] = Field(default_factory=list)
    conflict_assessments: list[ConflictAssessment] = Field(default_factory=list)


class CommandResult(DTO):
    operation_id: UUID
    run_id: UUID
    cycle: int

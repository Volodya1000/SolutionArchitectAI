from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.structured_models import StructuredMode
from solution_architect_ai.application.validation.source_language import validate_source_language
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory
from solution_architect_ai.domain.runs import RunStatus

type Content = Annotated[str, StringConstraints(min_length=1, max_length=8000)]
type StatementCategory = Literal[
    RequirementCategory.FUNCTIONAL,
    RequirementCategory.NON_FUNCTIONAL,
    RequirementCategory.BUSINESS_GOAL,
    RequirementCategory.SYSTEM_BOUNDARY,
    RequirementCategory.STAKEHOLDER,
    RequirementCategory.DATA,
    RequirementCategory.CONSTRAINT,
]


class Evidence(DTO):
    fragment_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    quote: Content


class ExtractedRequirement(DTO):
    category: StatementCategory
    original_text: Content
    normalized_text: Content = Field(
        description="Clear statement in the language of the cited source. Never translate it."
    )
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=20)]


class ExtractedGap(DTO):
    description: Content = Field(
        description="Unresolved information, in the cited source language."
    )
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=20)]


class ExtractedContradiction(DTO):
    description: Content = Field(
        description="Conflicting statements, in the cited source language."
    )
    evidence: Annotated[list[Evidence], Field(min_length=2, max_length=20)]


class RequirementsExtraction(DTO):
    requirements: Annotated[list[ExtractedRequirement], Field(max_length=500)]
    gaps: Annotated[list[ExtractedGap], Field(max_length=100)]
    contradictions: Annotated[list[ExtractedContradiction], Field(max_length=100)]

    @model_validator(mode="after")
    def preserve_source_language(self) -> Self:
        requirement: ExtractedRequirement
        for requirement in self.requirements:
            source: str = " ".join(evidence.quote for evidence in requirement.evidence)
            validate_source_language(source, requirement.original_text)
            validate_source_language(source, requirement.normalized_text)
        issue: ExtractedGap | ExtractedContradiction
        issues: tuple[ExtractedGap | ExtractedContradiction, ...] = (
            *self.gaps,
            *self.contradictions,
        )
        for issue in issues:
            validate_source_language(
                " ".join(evidence.quote for evidence in issue.evidence), issue.description
            )
        return self


class LocatorView(DTO):
    kind: str
    start: int
    end: int
    section: str
    path: str = ""


class SourceRef(DTO):
    file_id: UUID | None
    version_id: UUID | None
    sha256: str | None
    fragment_id: str
    locator: LocatorView | None
    quote: str
    status: EvidenceStatus
    reason: str | None


class RequirementView(DTO):
    id: UUID
    category: RequirementCategory
    original_text: str
    normalized_text: str
    sources: list[SourceRef]
    status: Literal["needs_review"] = "needs_review"


class ExtractionStart(DTO):
    operation_id: UUID
    version_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    analysis_scope: Annotated[str, StringConstraints(max_length=1000)] = ""
    answer_history_mode: Literal["reuse", "new"] = "reuse"
    answer_history_id: UUID | None = None


class AnswerHistorySelection(DTO):
    mode: Literal["reuse", "new"] = "reuse"
    history_id: UUID | None = None


class ExtractionProgress(DTO):
    completed_parts: int = 0
    total_parts: int = 0


class CoverageView(DTO):
    complete: bool = False
    total_fragments: int = 0
    processed_fragments: int = 0
    warnings: list[str] = Field(default_factory=list)


class StoredRetryProfile(DTO):
    network_retries: int
    validation_retries: int
    max_total_requests: int
    deadline_seconds: float
    request_timeout_seconds: float
    backoff_initial: float
    backoff_max: float
    jitter: float


class StoredModelProfile(DTO):
    base_url: str
    model: str
    context_window: int
    output_limit: int
    temperature: float
    approximate_chars_per_token: float
    concurrency: int
    structured_mode: StructuredMode
    service_tokens: int
    retry: StoredRetryProfile


class ExtractionSummary(DTO):
    id: UUID
    status: RunStatus
    progress: ExtractionProgress
    error_code: str | None
    created_at: datetime
    model: str
    version_ids: list[UUID] = Field(default_factory=list)
    analysis_scope: str = ""
    configuration_current: bool = False


class StoredExtractionSummary(ExtractionSummary):
    model_profile: StoredModelProfile
    contract_version: str
    prompt_version: str


class ExtractionHistory(DTO):
    items: list[ExtractionSummary]
    has_more: bool


class ExtractionMatches(DTO):
    active: ExtractionSummary | None
    current_completed: ExtractionSummary | None
    latest_completed: ExtractionSummary | None


class StoredExtractionMatches(DTO):
    active: StoredExtractionSummary | None
    current_completed: StoredExtractionSummary | None
    latest_completed: StoredExtractionSummary | None


class ExtractionView(StoredExtractionSummary):
    coverage: CoverageView
    requirements: list[RequirementView]
    requests: int = 0
    network_failures: int = 0
    corrections: int = 0
    elapsed_seconds: float = 0
    candidates_saved: bool = False


class PartResult(DTO):
    part_id: str
    requirements: list[RequirementView]
    fragment_ids: list[str]

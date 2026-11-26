from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

type AnnotationStatus = Literal["provisional", "confirmed"]


class EvaluationModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", strict=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class SourceEvidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)
    status: Literal["verified", "unverified"]


class Prediction(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)
    id: UUID
    sources: list[SourceEvidence]


class Progress(EvaluationModel):
    completed_parts: int = Field(ge=0)
    total_parts: int = Field(ge=0)


class Coverage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)
    complete: bool
    total_fragments: int = Field(ge=0)
    processed_fragments: int = Field(ge=0)


class RunRecord(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore", strict=True, hide_input_in_errors=True, allow_inf_nan=False
    )
    id: UUID
    created_at: datetime
    model: str
    status: Literal["queued", "running", "cancelling", "completed", "failed", "cancelled"]
    coverage: Coverage
    progress: Progress
    requirements: list[Prediction]
    requests: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    validated_responses: int | None = Field(default=None, ge=0)
    network_failures: int | None = Field(default=None, ge=0)
    corrections: int | None = Field(default=None, ge=0)


class GoldRequirement(EvaluationModel):
    id: str = Field(min_length=1)
    category: Literal[
        "functional",
        "non_functional",
        "business_goal",
        "system_boundary",
        "stakeholder",
        "data",
        "constraint",
        "gap",
        "contradiction",
    ]
    description: str = Field(min_length=1)
    quotes: list[str] = Field(min_length=1)


class GoldSet(EvaluationModel):
    source: str
    annotation_status: AnnotationStatus
    requirements: list[GoldRequirement]


class ManualMapping(RootModel[dict[UUID, list[str]]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)


class Metric(EvaluationModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None


class Evaluation(EvaluationModel):
    schema_version: Literal["pr2-evaluation-1"] = "pr2-evaluation-1"
    run_id: UUID
    run_created_at: datetime
    measured_at: datetime
    model: str
    status: str
    gold_source: str
    annotation_status: AnnotationStatus
    metrics: dict[str, Metric]
    false_positive_predictions: list[UUID]
    unmatched_gold: list[str]
    duplicate_gold_assignments: int
    reserved_requests: int
    network_failures: int | None
    corrections: int | None
    elapsed_seconds: float
    validation_rate_basis: Literal["response_counter", "persisted_parts_lower_bound"]
    coverage_complete: bool
    notes: list[str]

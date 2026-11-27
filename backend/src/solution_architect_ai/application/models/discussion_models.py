from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.extraction_models import SourceRef


class RequirementSubject(DTO):
    kind: Literal["requirement"]
    run_id: UUID
    requirement_id: UUID


class SourceSubject(DTO):
    kind: Literal["source"]
    version_id: UUID
    fragment_id: UUID
    analysis_id: UUID | None = None


type DiscussionSubject = Annotated[RequirementSubject | SourceSubject, Field(discriminator="kind")]


class CreateDiscussion(DTO):
    operation_id: UUID
    subject: DiscussionSubject


class DiscussionView(DTO):
    chat_id: UUID
    kind: Literal["requirement", "source"]
    title: str
    analysis_id: UUID | None
    requirement_id: UUID | None
    version_id: UUID | None
    fragment_id: UUID | None
    version_ids: list[UUID]
    history_id: UUID | None
    backlink: str


class DiscussionBinding(DTO):
    view: DiscussionView
    sources: list[SourceRef]

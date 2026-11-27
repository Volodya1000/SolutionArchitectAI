from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.domain.documents import ParsedDocument


class UploadStage(StrEnum):
    PREPARED = "prepared"
    COMPLETED = "completed"


class UploadDocument(DTO):
    operation_id: UUID
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    mime_type: str
    file_id: UUID | None = None


class DocumentVersionView(DTO):
    file_id: UUID
    version_id: UUID
    task_id: UUID
    sha256: str
    mime_type: str
    size: int
    original_name: str
    uploaded_at: datetime
    storage_key: str


class DocumentView(DTO):
    file_id: UUID
    task_id: UUID
    name: str
    created_at: datetime
    latest_version: DocumentVersionView | None = None


class UploadOperationView(DTO):
    operation_id: UUID
    payload_digest: str
    stage: UploadStage
    version: DocumentVersionView
    diagnostic: str | None = None


class StoredParse(DTO):
    document: ParsedDocument
    digest: str


class AttachDocument(DTO):
    version_id: UUID


class DocumentErrorView(DTO):
    code: str = Field(min_length=1)

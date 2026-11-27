from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from solution_architect_ai.persistence.models import Base


class DocumentRow(Base):
    __tablename__: str = "documents"
    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentVersionRow(Base):
    __tablename__: str = "document_versions"
    version_id: Mapped[UUID] = mapped_column(primary_key=True)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("documents.file_id"), index=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str]
    size: Mapped[int]
    original_name: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    storage_key: Mapped[str] = mapped_column(unique=True)


class DocumentUploadRow(Base):
    __tablename__: str = "document_uploads"
    __table_args__: tuple[UniqueConstraint, ...] = (UniqueConstraint("task_id", "operation_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    operation_id: Mapped[UUID]
    payload_digest: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str]
    version_json: Mapped[str]


class ParsedDocumentRow(Base):
    __tablename__: str = "parsed_documents"
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.version_id"), primary_key=True
    )
    parser_version: Mapped[str]
    body: Mapped[str]
    digest: Mapped[str] = mapped_column(String(64))


class DocumentFragmentRow(Base):
    __tablename__: str = "document_fragments"
    fragment_id: Mapped[UUID] = mapped_column(primary_key=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("parsed_documents.version_id"), index=True)
    text: Mapped[str]
    locator_json: Mapped[str]


class MessageDocumentVersionRow(Base):
    __tablename__: str = "message_document_versions"
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.version_id"), primary_key=True
    )

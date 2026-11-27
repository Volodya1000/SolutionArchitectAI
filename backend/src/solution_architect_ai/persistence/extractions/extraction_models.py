from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from solution_architect_ai.persistence.models import Base, now


class ExtractionRow(Base):
    __tablename__: str = "requirements_extractions"
    __table_args__: tuple[UniqueConstraint, ...] = (UniqueConstraint("task_id", "operation_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    operation_id: Mapped[UUID]
    payload_digest: Mapped[str]
    config_digest: Mapped[str]
    context_digest: Mapped[str | None]
    command_json: Mapped[str]
    snapshot_json: Mapped[str]
    status: Mapped[str] = mapped_column(index=True)
    requests: Mapped[int] = mapped_column(default=0)
    network_failures: Mapped[int] = mapped_column(default=0)
    corrections: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractionPartRow(Base):
    __tablename__: str = "requirements_extraction_parts"
    __table_args__: tuple[UniqueConstraint, ...] = (UniqueConstraint("run_id", "part_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("requirements_extractions.id"), index=True)
    part_id: Mapped[str]
    result_json: Mapped[str]


class RequirementRow(Base):
    __tablename__: str = "requirements"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("requirements_extractions.id"), index=True)
    category: Mapped[str]
    original_text: Mapped[str]
    normalized_text: Mapped[str]
    sources_json: Mapped[str]
    review_status: Mapped[str]


class ExtractionSourceRow(Base):
    __tablename__: str = "requirements_extraction_sources"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements_extractions.id"), primary_key=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.version_id"), primary_key=True
    )

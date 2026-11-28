from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from solution_architect_ai.persistence.models import Base


class ClarificationRunRow(Base):
    __tablename__: str = "clarification_runs"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements_extractions.id"), primary_key=True
    )
    history_id: Mapped[UUID] = mapped_column(index=True)
    cycle: Mapped[int] = mapped_column(default=0)
    initialized: Mapped[bool] = mapped_column(default=False)
    resume_pending: Mapped[bool] = mapped_column(default=False)
    resume_version: Mapped[int] = mapped_column(default=0)
    metadata_json: Mapped[str | None]
    completed_json: Mapped[str] = mapped_column(default="[]")
    active_seconds: Mapped[float] = mapped_column(default=0.0)
    active_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assessments_json: Mapped[str] = mapped_column(default="[]")


class ClarificationStepRow(Base):
    __tablename__: str = "clarification_review_steps"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements_extractions.id"), primary_key=True
    )
    step_key: Mapped[str] = mapped_column(primary_key=True)
    result_json: Mapped[str]


class QuestionRow(Base):
    __tablename__: str = "clarification_questions"
    __table_args__: tuple[UniqueConstraint, ...] = (
        UniqueConstraint("task_id", "history_id", "gap_key"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    history_id: Mapped[UUID]
    gap_key: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


class QuestionRevisionRow(Base):
    __tablename__: str = "clarification_question_revisions"
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("clarification_questions.id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]
    snapshot_json: Mapped[str]


class QuestionLinkRow(Base):
    __tablename__: str = "clarification_question_links"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("clarification_runs.run_id"), primary_key=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("clarification_questions.id"), primary_key=True
    )
    revision: Mapped[int]
    requirement_ids_json: Mapped[str]
    sources_json: Mapped[str | None]


class DecisionRow(Base):
    __tablename__: str = "clarification_decisions"
    __table_args__: tuple[UniqueConstraint, ...] = (
        UniqueConstraint("question_id", "question_revision"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("clarification_questions.id"))
    question_revision: Mapped[int]
    run_id: Mapped[UUID] = mapped_column(ForeignKey("clarification_runs.run_id"))
    snapshot_json: Mapped[str]


class RiskRow(Base):
    __tablename__: str = "clarification_risks"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("clarification_decisions.id"), unique=True)
    snapshot_json: Mapped[str]


class ClarificationOperationRow(Base):
    __tablename__: str = "clarification_operations"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(primary_key=True)
    digest: Mapped[str]
    kind: Mapped[str]
    result_json: Mapped[str]

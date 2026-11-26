from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from solution_architect_ai.domain.runs import RunStatus


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__: str = "projects"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str]


class TaskRow(Base):
    __tablename__: str = "tasks"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str]


class ChatRow(Base):
    __tablename__: str = "chats"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageRow(Base):
    __tablename__: str = "messages"
    __table_args__: tuple[UniqueConstraint, ...] = (UniqueConstraint("chat_id", "position"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str]
    content: Mapped[str] = mapped_column(default="")
    position: Mapped[int]
    incomplete: Mapped[bool] = mapped_column(default=False)


class RunRow(Base):
    __tablename__: str = "runs"
    __table_args__: tuple[UniqueConstraint, ...] = (
        UniqueConstraint("chat_id", "command_id"),
        UniqueConstraint("assistant_message_id", name="uq_runs_assistant_message_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), index=True)
    command_id: Mapped[UUID]
    payload_digest: Mapped[str]
    assistant_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    status: Mapped[str] = mapped_column(default=RunStatus.QUEUED.value, index=True)
    sequence: Mapped[int] = mapped_column(default=0)
    incomplete: Mapped[bool] = mapped_column(default=True)
    error_code: Mapped[str | None]
    model: Mapped[str]
    config_digest: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PreferenceRow(Base):
    __tablename__: str = "preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(default="system")

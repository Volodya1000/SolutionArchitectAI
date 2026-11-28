from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from solution_architect_ai.persistence.models import Base


class DiscussionRow(Base):
    __tablename__: str = "discussions"
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), primary_key=True)
    binding_json: Mapped[str]


class DiscussionOperationRow(Base):
    __tablename__: str = "discussion_operations"
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(primary_key=True)
    author_id: Mapped[UUID]
    command_json: Mapped[str]
    result_json: Mapped[str]

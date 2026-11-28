from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus

type Theme = Literal["light", "dark", "system"]
type Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]


class DTO(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )


class ChatCreate(DTO):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class StartRun(DTO):
    command_id: UUID
    content: Text


class ChatView(DTO):
    id: UUID
    task_id: UUID
    title: str
    created_at: datetime


class MessageView(DTO):
    id: UUID
    role: MessageRole
    content: str
    position: int
    incomplete: bool


class PendingRun(DTO):
    id: UUID
    status: RunStatus
    created_at: datetime


class RunView(DTO):
    id: UUID
    chat_id: UUID
    assistant_message_id: UUID
    status: RunStatus
    sequence: int
    content: str
    incomplete: bool

    error_code: RunErrorCode | str | None
    model: str
    config_digest: str
    created_at: datetime


class RunSnapshotEvent(DTO):
    run_id: UUID
    sequence: int
    kind: Literal["snapshot"] = "snapshot"
    payload: RunView


class ChatSnapshot(DTO):
    chat: ChatView
    messages: list[MessageView]
    runs: list[RunView]


class Preferences(DTO):
    theme: Theme = "system"


class ModelStatus(DTO):
    model: str
    available: bool


class APIError(DTO):
    code: Literal["not_found", "conflict", "database_unavailable"]


class HealthStatus(DTO):
    status: Literal["alive", "ready"]

"""Compatibility imports during the API module split."""

from solution_architect_ai.application.dto import (
    DTO,
    ChatCreate,
    ChatSnapshot,
    ChatView,
    MessageView,
    ModelStatus,
    Preferences,
    Role,
    RunSnapshotEvent,
    RunView,
    StartRun,
    Text,
    Theme,
)
from solution_architect_ai.application.errors import (
    ChatError,
    Conflict,
    Missing,
    StorageUnavailable,
)

__all__: tuple[str, ...] = (
    "DTO",
    "ChatCreate",
    "ChatError",
    "ChatSnapshot",
    "ChatView",
    "Conflict",
    "MessageView",
    "Missing",
    "ModelStatus",
    "Preferences",
    "Role",
    "RunSnapshotEvent",
    "RunView",
    "StartRun",
    "StorageUnavailable",
    "Text",
    "Theme",
)

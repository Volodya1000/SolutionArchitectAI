from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from solution_architect_ai.application.dto import (
    ChatSnapshot,
    ChatView,
    MessageView,
    ModelStatus,
    PendingRun,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus


class ChatQueries(Protocol):
    async def list_chats(self) -> list[ChatView]: ...
    async def snapshot(self, chat_id: UUID) -> ChatSnapshot: ...
    async def get_run(self, run_id: UUID) -> RunView: ...
    async def pending(self) -> list[PendingRun]: ...
    async def preferences(self) -> Preferences: ...
    async def ready(self) -> None: ...


class ChatStore(Protocol):
    @property
    def queries(self) -> ChatQueries: ...

    async def create_chat(self, title: str) -> ChatView: ...
    async def start(self, chat_id: UUID, command: StartRun, model: str, digest: str) -> RunView: ...
    async def set_status(
        self, run_id: UUID, target: RunStatus, error: RunErrorCode | None = None
    ) -> RunView: ...
    async def append(self, run_id: UUID, text: str) -> bool: ...
    async def update_preferences(self, value: Preferences) -> Preferences: ...


class StoreFactory(Protocol):
    def open(self) -> AbstractAsyncContextManager[ChatStore]: ...


class ResourceProbe(Protocol):
    async def check(self) -> None: ...


@dataclass(frozen=True)
class Chunk:
    text: str = ""
    finish: str | None = None


class TokenCounter(Protocol):
    def count(self, messages: list[MessageView]) -> int: ...


class LLM(Protocol):
    async def status(self) -> ModelStatus: ...

    def stream(
        self, messages: list[MessageView]
    ) -> AbstractAsyncContextManager[AsyncIterator[Chunk]]: ...

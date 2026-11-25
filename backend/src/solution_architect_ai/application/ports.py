from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from solution_architect_ai.application.contracts import (
    ChatSnapshot,
    ChatView,
    MessageView,
    ModelStatus,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.domain.runs import RunStatus


# This port keeps application use cases independent of SQL sessions and ORM entities.
class ChatStore(Protocol):
    async def list_chats(self) -> list[ChatView]: ...
    async def create_chat(self, title: str) -> ChatView: ...
    async def snapshot(self, chat_id: UUID) -> ChatSnapshot: ...
    async def start(self, chat_id: UUID, command: StartRun, model: str, digest: str) -> RunView: ...
    async def get_run(self, run_id: UUID) -> RunView: ...
    async def pending(self) -> list[RunView]: ...
    async def set_status(
        self, run_id: UUID, target: RunStatus, error: str | None = None
    ) -> RunView: ...
    async def append(self, run_id: UUID, text: str) -> bool: ...
    async def preferences(self, value: Preferences | None = None) -> Preferences: ...
    async def ready(self) -> None: ...


class StoreFactory(Protocol):
    def open(self) -> AbstractAsyncContextManager[ChatStore]: ...


# Readiness must check durable volumes without coupling use cases to filesystem I/O.
class ResourceProbe(Protocol):
    async def check(self) -> None: ...


@dataclass(frozen=True)
class Chunk:
    text: str = ""
    finish: str | None = None


# A context manager guarantees cleanup when generation is cancelled or truncated.
class LLM(Protocol):
    async def status(self) -> ModelStatus: ...

    def stream(
        self, messages: list[MessageView]
    ) -> AbstractAsyncContextManager[AsyncIterator[Chunk]]: ...


class GenerationFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: float = 0) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after

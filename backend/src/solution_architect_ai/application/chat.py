from uuid import UUID

from solution_architect_ai.application.contracts import (
    ChatSnapshot,
    ChatView,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.application.ports import ResourceProbe, StoreFactory
from solution_architect_ai.domain.runs import RunStatus


class ChatService:
    def __init__(self, stores: StoreFactory, model: str, digest: str, probe: ResourceProbe) -> None:
        self.stores = stores
        self.model = model
        self.digest = digest
        self.probe = probe

    async def list_chats(self) -> list[ChatView]:
        async with self.stores.open() as store:
            return await store.list_chats()

    async def create(self, title: str) -> ChatView:
        async with self.stores.open() as store:
            return await store.create_chat(title)

    async def snapshot(self, chat_id: UUID) -> ChatSnapshot:
        async with self.stores.open() as store:
            return await store.snapshot(chat_id)

    async def start(self, chat_id: UUID, command: StartRun) -> RunView:
        async with self.stores.open() as store:
            return await store.start(chat_id, command, self.model, self.digest)

    async def run(self, run_id: UUID) -> RunView:
        async with self.stores.open() as store:
            return await store.get_run(run_id)

    async def cancel(self, run_id: UUID) -> RunView:
        async with self.stores.open() as store:
            return await store.set_status(run_id, RunStatus.CANCELLING)

    async def preferences(self) -> Preferences:
        async with self.stores.open() as store:
            return await store.preferences()

    async def update_preferences(self, value: Preferences) -> Preferences:
        async with self.stores.open() as store:
            return await store.update_preferences(value)

    async def ready(self) -> None:
        async with self.stores.open() as store:
            await store.ready()
        await self.probe.check()

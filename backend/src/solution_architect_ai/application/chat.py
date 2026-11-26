from uuid import UUID

from solution_architect_ai.application.dto import (
    RunView,
    StartRun,
)
from solution_architect_ai.application.ports import ChatStore, ResourceProbe, StoreFactory
from solution_architect_ai.domain.runs import RunStatus


class ChatService:
    def __init__(self, stores: StoreFactory, model: str, digest: str, probe: ResourceProbe) -> None:
        self.stores: StoreFactory = stores
        self.model: str = model
        self.digest: str = digest
        self.probe: ResourceProbe = probe

    async def start(self, chat_id: UUID, command: StartRun) -> RunView:
        store: ChatStore
        async with self.stores.open() as store:
            return await store.start(chat_id, command, self.model, self.digest)

    async def run(self, run_id: UUID) -> RunView:
        store: ChatStore
        async with self.stores.open() as store:
            return await store.queries.get_run(run_id)

    async def cancel(self, run_id: UUID) -> RunView:
        store: ChatStore
        async with self.stores.open() as store:
            return await store.set_status(run_id, RunStatus.CANCELLING)

    async def ready(self) -> None:
        store: ChatStore
        async with self.stores.open() as store:
            await store.queries.ready()
        await self.probe.check()

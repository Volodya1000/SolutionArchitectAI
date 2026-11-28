from uuid import UUID

from solution_architect_ai.application.models.chat_dto import (
    RunView,
    StartRun,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore, ResourceProbe
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.domain.runs import RunStatus


class ChatService:
    def __init__(
        self,
        chat_store_context: StoreContext[ChatStore],
        model: str,
        config_digest: str,
        resource_probe: ResourceProbe,
    ) -> None:
        self.chat_store_context: StoreContext[ChatStore] = chat_store_context
        self.model: str = model
        self.config_digest: str = config_digest
        self.resource_probe: ResourceProbe = resource_probe

    async def start(self, chat_id: UUID, command: StartRun) -> RunView:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            return await store.start(chat_id, command, self.model, self.config_digest)

    async def run(self, run_id: UUID) -> RunView:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            return await store.queries.get_run(run_id)

    async def cancel(self, run_id: UUID) -> RunView:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            return await store.set_status(run_id, RunStatus.CANCELLING)

    async def ready(self) -> None:
        store: ChatStore
        async with self.chat_store_context.open() as store:
            await store.queries.ready()
        await self.resource_probe.check()

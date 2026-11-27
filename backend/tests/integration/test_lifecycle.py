import asyncio
import os
from typing import Final

import pytest
from dishka import AsyncContainer, make_async_container
from sqlalchemy import URL, AsyncAdaptedQueuePool, Pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.tests.sql_store_setup import SqlStoreSetup, chat_store_setup
from solution_architect_ai.application.errors.chat_errors import StorageUnavailable
from solution_architect_ai.application.models.chat_dto import ChatView
from solution_architect_ai.application.protocols.chat_protocols import ChatStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


def checked_out(engine: AsyncEngine) -> int:
    pool: Pool = engine.pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    return pool.checkedout()


async def write_then_fail(stores: StoreContext[ChatStore]) -> None:
    store: ChatStore
    async with stores.open() as store:
        await store.create_chat("Откатить этот чат")
        raise RuntimeError("rollback")


async def test_factory_commits_success_rolls_back_failure_and_releases_connections() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: bootstrap()})
    try:
        engine: AsyncEngine = await container.get(AsyncEngine)
        stores: StoreContext[ChatStore] = await container.get(StoreContext[ChatStore])
        store: ChatStore
        async with stores.open() as store:
            chat: ChatView = await store.create_chat("Сохранённый чат")
        assert checked_out(engine) == 0
        with pytest.raises(RuntimeError, match="rollback"):
            await write_then_fail(stores)
        async with stores.open() as store:
            chats: list[ChatView] = await store.queries.list_chats()
        assert any(item.id == chat.id for item in chats)
        assert all(item.title != "Откатить этот чат" for item in chats)
        assert checked_out(engine) == 0
    finally:
        await container.close()


async def test_cancellation_rolls_back_and_releases_session() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: bootstrap()})
    entered: asyncio.Event = asyncio.Event()
    try:
        engine: AsyncEngine = await container.get(AsyncEngine)
        stores: StoreContext[ChatStore] = await container.get(StoreContext[ChatStore])

        async def interrupted() -> None:
            store: ChatStore
            async with stores.open() as store:
                await store.create_chat("Отменённая транзакция")
                entered.set()
                await asyncio.Event().wait()

        tasks: asyncio.TaskGroup
        async with asyncio.TaskGroup() as tasks:
            pending: asyncio.Task[None] = tasks.create_task(interrupted())
            async with asyncio.timeout(5):
                await entered.wait()
            pending.cancel()
        store: ChatStore
        async with stores.open() as store:
            chats: list[ChatView] = await store.queries.list_chats()
        assert all(item.title != "Отменённая транзакция" for item in chats)
        assert checked_out(engine) == 0
    finally:
        await container.close()


async def test_failed_connection_initialization_releases_pool_slot() -> None:
    url: URL = URL.create("postgresql+psycopg", username="test", host="127.0.0.1", port=1)
    engine: AsyncEngine = create_async_engine(url, connect_args={"connect_timeout": 1})
    stores: SqlStoreSetup[SqlAlchemyStore] = chat_store_setup(
        async_sessionmaker[AsyncSession](engine)
    )
    try:
        store: ChatStore
        with pytest.raises(StorageUnavailable):
            async with stores.open() as store:
                await store.queries.list_chats()
        assert checked_out(engine) == 0
    finally:
        await engine.dispose()

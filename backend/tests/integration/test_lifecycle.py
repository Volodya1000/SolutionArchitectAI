import asyncio
import os

import pytest
from dishka import make_async_container
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from solution_architect_ai.application.contracts import StorageUnavailable
from solution_architect_ai.application.ports import StoreFactory
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.persistence.factory import SqlAlchemyStoreFactory

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def write_then_fail(stores: StoreFactory) -> None:
    async with stores.open() as store:
        await store.create_chat("Откатить этот чат")
        raise RuntimeError("rollback")


async def test_factory_commits_success_rolls_back_failure_and_releases_connections() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container = make_async_container(AppProvider(), context={Settings: bootstrap()})
    try:
        engine = await container.get(AsyncEngine)
        stores = await container.get(StoreFactory)
        async with stores.open() as store:
            chat = await store.create_chat("Сохранённый чат")
        assert engine.pool.checkedout() == 0
        with pytest.raises(RuntimeError, match="rollback"):
            await write_then_fail(stores)
        async with stores.open() as store:
            chats = await store.list_chats()
        assert any(item.id == chat.id for item in chats)
        assert all(item.title != "Откатить этот чат" for item in chats)
        assert engine.pool.checkedout() == 0
    finally:
        await container.close()


async def test_cancellation_rolls_back_and_releases_session() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container = make_async_container(AppProvider(), context={Settings: bootstrap()})
    entered = asyncio.Event()
    try:
        engine = await container.get(AsyncEngine)
        stores = await container.get(StoreFactory)

        async def interrupted() -> None:
            async with stores.open() as store:
                await store.create_chat("Отменённая транзакция")
                entered.set()
                await asyncio.Event().wait()

        async with asyncio.TaskGroup() as tasks:
            pending = tasks.create_task(interrupted())
            async with asyncio.timeout(5):
                await entered.wait()
            pending.cancel()
        async with stores.open() as store:
            chats = await store.list_chats()
        assert all(item.title != "Отменённая транзакция" for item in chats)
        assert engine.pool.checkedout() == 0
    finally:
        await container.close()


async def test_failed_connection_initialization_releases_pool_slot() -> None:
    url = URL.create(
        "postgresql+psycopg", username="test", password="local-test", host="127.0.0.1", port=1
    )
    engine = create_async_engine(url, connect_args={"connect_timeout": 1})
    stores = SqlAlchemyStoreFactory(async_sessionmaker[AsyncSession](engine))
    try:
        with pytest.raises(StorageUnavailable):
            async with stores.open() as store:
                await store.list_chats()
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()

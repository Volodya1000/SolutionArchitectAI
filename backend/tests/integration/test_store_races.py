import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from dishka import make_async_container
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.contracts import StartRun
from solution_architect_ai.application.ports import StoreFactory
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.store import PostgresStore

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def resources() -> AsyncIterator[tuple[StoreFactory, AsyncEngine]]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container = make_async_container(AppProvider(), context={Settings: bootstrap()})
    try:
        yield await container.get(StoreFactory), await container.get(AsyncEngine)
    finally:
        await container.close()


async def test_cancel_wins_before_worker_claims_run(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, _ = resources
    async with stores.open() as store:
        chat = await store.create_chat("Гонка отмены")
        run = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
    async with stores.open() as store:
        stale = await store.get_run(run.id)
        assert stale.status == RunStatus.QUEUED
        async with stores.open() as cancelling:
            await cancelling.set_status(run.id, RunStatus.CANCELLING)
        claimed = await store.set_status(run.id, RunStatus.RUNNING)
    assert claimed.status == RunStatus.CANCELLING
    async with stores.open() as store:
        await store.set_status(run.id, RunStatus.CANCELLED)


async def test_snapshot_never_pairs_terminal_status_with_older_message(
    resources: tuple[StoreFactory, AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    stores, engine = resources
    async with stores.open() as store:
        chat = await store.create_chat("Согласованный снимок")
        run = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
        await store.set_status(run.id, RunStatus.RUNNING)
        await store.append(run.id, "Начало")
    sessions = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        original = session.execute
        interleaved = False

        async def execute(*args: Any, **kwargs: Any) -> Any:
            nonlocal interleaved
            result = await original(*args, **kwargs)
            if not interleaved and "FROM messages" in str(args[0]):
                interleaved = True
                async with stores.open() as writer:
                    await writer.append(run.id, " и конец")
                    await writer.set_status(run.id, RunStatus.COMPLETED)
            return result

        monkeypatch.setattr(session, "execute", execute)
        snapshot = await PostgresStore(session).snapshot(chat.id)
        assert interleaved
        answer = snapshot.messages[-1]
        view = snapshot.runs[-1]
        assert view.content == answer.content
        assert view.incomplete == answer.incomplete
        if view.status == RunStatus.COMPLETED:
            assert answer.content == "Начало и конец"

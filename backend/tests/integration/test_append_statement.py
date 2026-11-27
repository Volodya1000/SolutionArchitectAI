import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.models.chat_dto import ChatView, RunView, StartRun
from solution_architect_ai.application.protocols.chat_protocols import ChatStore, StoreFactory
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: list[pytest.MarkDecorator] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class Running:
    run_id: UUID
    stores: StoreFactory
    engine: AsyncEngine


@pytest.fixture(name="running")
async def running_store() -> AsyncIterator[Running]:
    settings: Settings = bootstrap()
    assert settings.database.database.endswith("_test")
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: settings})
    try:
        stores: StoreFactory = await container.get(StoreFactory)
        engine: AsyncEngine = await container.get(AsyncEngine)
        store: ChatStore
        async with stores.open() as store:
            chat: ChatView = await store.create_chat("Append")
            run: RunView = await store.start(
                chat.id, StartRun(command_id=uuid4(), content="Q"), "fake", "x"
            )
            await store.set_status(run.id, RunStatus.RUNNING)
        try:
            yield Running(run.id, stores, engine)
        finally:
            async with stores.open() as store:
                await store.set_status(run.id, RunStatus.FAILED)
    finally:
        await container.close()


async def test_append_persists_each_delta_in_one_statement(running: Running) -> None:
    statements: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        statements.append(statement)

    store: ChatStore
    event.listen(running.engine.sync_engine, "before_cursor_execute", record)
    try:
        async with running.stores.open() as store:
            assert await store.append(running.run_id, "first")
    finally:
        event.remove(running.engine.sync_engine, "before_cursor_execute", record)
    async with running.stores.open() as store:
        view: RunView = await store.set_status(running.run_id, RunStatus.CANCELLING)
        assert view.content == "first"
        assert not await store.append(running.run_id, "late")
        await store.set_status(running.run_id, RunStatus.CANCELLED)
    assert len(statements) == 1


async def test_append_rejects_runs_outside_the_store_task(running: Running) -> None:
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(running.engine)
    session: AsyncSession
    async with sessions.begin() as session:
        scoped: SqlAlchemyStore = SqlAlchemyStore(session, task_id=uuid4())
        with pytest.raises(Missing, match="run"):
            await scoped.append(running.run_id, "out of scope")
    store: ChatStore
    async with running.stores.open() as store:
        assert (await store.queries.get_run(running.run_id)).content == ""


async def backend_pid(session: AsyncSession) -> int:
    pid: object = await session.scalar(text("SELECT pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


async def append_after_cancel(
    running: Running, sessions: async_sessionmaker[AsyncSession], writer_pid: asyncio.Future[int]
) -> bool:
    writer: AsyncSession
    async with sessions.begin() as writer:
        writer_pid.set_result(await backend_pid(writer))
        return await SqlAlchemyStore(writer).append(running.run_id, "late")


async def wait_for_blocker(engine: AsyncEngine, writer_pid: int, blocker_pid: int) -> None:
    observer: AsyncConnection
    async with engine.connect() as observer:
        while True:
            blocked: bool | None = await observer.scalar(
                text("SELECT :blocker = ANY(pg_blocking_pids(:writer))"),
                {"blocker": blocker_pid, "writer": writer_pid},
            )
            if blocked:
                return
            await asyncio.sleep(0.01)


async def test_append_waiting_for_cancel_rechecks_status(running: Running) -> None:
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(running.engine)
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    tasks: asyncio.TaskGroup
    owner: AsyncSession

    async with asyncio.timeout(5), asyncio.TaskGroup() as tasks, sessions.begin() as owner:
        store: SqlAlchemyStore = SqlAlchemyStore(owner)
        assert await store.append(running.run_id, "first")
        cancelling: RunView = await store.set_status(running.run_id, RunStatus.CANCELLING)
        owner_pid: int = await backend_pid(owner)
        late: asyncio.Task[bool] = tasks.create_task(
            append_after_cancel(running, sessions, writer_pid)
        )
        await wait_for_blocker(running.engine, await writer_pid, owner_pid)

    assert not late.result()
    reader: ChatStore
    async with running.stores.open() as reader:
        assert await reader.queries.get_run(running.run_id) == cancelling
        terminal: RunView = await reader.set_status(running.run_id, RunStatus.CANCELLED)
        assert terminal.status == RunStatus.CANCELLED
        assert terminal.sequence == cancelling.sequence + 1
        assert terminal.content == "first"
        assert not await reader.append(running.run_id, "after cancellation")
        assert await reader.queries.get_run(running.run_id) == terminal

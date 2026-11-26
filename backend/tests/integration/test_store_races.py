import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from dishka import make_async_container
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.contracts import (
    Missing,
    Preferences,
    StartRun,
    StorageUnavailable,
)
from solution_architect_ai.application.ports import StoreFactory
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.models import RunRow, TaskRow
from solution_architect_ai.persistence.store import SqlAlchemyStore

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
        snapshot = await SqlAlchemyStore(session).snapshot(chat.id)
        assert interleaved
        answer = snapshot.messages[-1]
        view = snapshot.runs[-1]
        assert view.content == answer.content
        assert view.incomplete == answer.incomplete
        if view.status == RunStatus.COMPLETED:
            assert answer.content == "Начало и конец"


def record_selects(engine: AsyncEngine, statements: list[str]) -> Any:
    def record(_connection: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    return record


async def test_pending_fetches_all_runs_in_one_statement(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, engine = resources
    created = []
    async with stores.open() as store:
        for index in range(2):
            chat = await store.create_chat(f"Pending {index}")
            created.append(
                await store.start(
                    chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
                )
            )
    statements: list[str] = []
    listener = record_selects(engine, statements)
    try:
        async with stores.open() as store:
            pending = await store.pending()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)
    assert {run.id for run in created} <= {run.id for run in pending}
    assert len(statements) == 1
    async with stores.open() as store:
        for run in created:
            await store.set_status(run.id, RunStatus.FAILED, "test_cleanup")


async def test_preference_reads_do_not_lock_and_writes_are_explicit(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, engine = resources
    statements: list[str] = []
    listener = record_selects(engine, statements)
    try:
        async with stores.open() as store:
            before = await store.preferences()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)
    assert all("FOR UPDATE" not in statement for statement in statements)
    async with stores.open() as store:
        await store.update_preferences(Preferences(theme="dark"))
    async with stores.open() as store:
        assert (await store.preferences()).theme == "dark"
        await store.update_preferences(before)


async def test_task_scope_applies_to_creating_listing_and_loading_chat(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, engine = resources
    async with stores.open() as store:
        local = await store.create_chat("Local task")
    sessions = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
    async with sessions() as session, session.begin():
        task = await session.scalar(select(TaskRow))
        assert task is not None
        task_id = uuid4()
        session.add(TaskRow(id=task_id, project_id=task.project_id, title="Other task"))
        await session.flush()
        scoped = SqlAlchemyStore(session, task_id=task_id)
        other = await scoped.create_chat("Scoped chat")
        assert other.task_id == task_id
        assert [chat.id for chat in await scoped.list_chats()] == [other.id]
        with pytest.raises(Missing):
            await scoped.snapshot(local.id)
        assert (await scoped.snapshot(other.id)).chat.id == other.id
        with pytest.raises(Missing):
            await SqlAlchemyStore(session).snapshot(other.id)


async def test_assistant_message_cannot_belong_to_two_runs(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, engine = resources
    async with stores.open() as store:
        chat = await store.create_chat("Unique answer")
        run = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
        await store.set_status(run.id, RunStatus.FAILED, "test_cleanup")
    sessions = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
    async with sessions() as session:
        session.add(
            RunRow(
                chat_id=chat.id,
                command_id=uuid4(),
                payload_digest="x",
                assistant_message_id=run.assistant_message_id,
                model="fake",
                config_digest="x",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_readiness_reports_stale_schema_as_storage_unavailable(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    _, engine = resources
    sessions = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
    async with sessions() as session:
        await SqlAlchemyStore(session).ready()
        await session.execute(text("UPDATE alembic_version SET version_num = '0001_chat'"))
        with pytest.raises(StorageUnavailable, match="schema"):
            await SqlAlchemyStore(session).ready()
        await session.rollback()


async def test_status_write_uses_loaded_rows_and_keeps_cancel_precedence(
    resources: tuple[StoreFactory, AsyncEngine],
) -> None:
    stores, engine = resources
    async with stores.open() as store:
        chat = await store.create_chat("Loaded rows")
        run = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
    statements: list[str] = []
    listener = record_selects(engine, statements)
    try:
        async with stores.open() as store:
            claimed = await store.set_status(run.id, RunStatus.RUNNING)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)
    assert claimed.status == RunStatus.RUNNING
    assert len(statements) == 2
    async with stores.open() as store:
        await store.append(run.id, "Частичный ответ")
        cancelling = await store.set_status(run.id, RunStatus.CANCELLING)
        late = await store.set_status(run.id, RunStatus.COMPLETED)
        assert late == cancelling
        cancelled = await store.set_status(run.id, RunStatus.CANCELLED)
        assert cancelled.content == "Частичный ответ"
        assert cancelled.incomplete

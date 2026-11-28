import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Final
from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from sqlalchemy import Result, Select, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from solution_architect_ai.application.errors.chat_errors import Missing, StorageUnavailable
from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    ChatView,
    MessageView,
    PendingRun,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.models import MessageRow, RunRow, TaskRow
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture(name="resources")
async def database_resources() -> AsyncIterator[tuple[StoreContext[ChatStore], AsyncEngine]]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: bootstrap()})
    try:
        yield await container.get(StoreContext[ChatStore]), await container.get(AsyncEngine)
    finally:
        await container.close()


async def test_cancel_wins_before_worker_claims_run(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore] = resources[0]
    store: ChatStore
    async with stores.open() as store:
        chat: ChatView = await store.create_chat("Гонка отмены")
        run: RunView = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
    async with stores.open() as store:
        stale: RunView = await store.queries.get_run(run.id)
        assert stale.status == RunStatus.QUEUED
        cancelling: ChatStore
        async with stores.open() as cancelling:
            await cancelling.set_status(run.id, RunStatus.CANCELLING)
        claimed: RunView = await store.set_status(run.id, RunStatus.RUNNING)
    assert claimed.status == RunStatus.CANCELLING
    async with stores.open() as store:
        await store.set_status(run.id, RunStatus.CANCELLED)


async def test_snapshot_never_pairs_terminal_status_with_older_message(
    resources: tuple[StoreContext[ChatStore], AsyncEngine], monkeypatch: pytest.MonkeyPatch
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    async with stores.open() as store:
        chat: ChatView = await store.create_chat("Согласованный снимок")
        run: RunView = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
        await store.set_status(run.id, RunStatus.RUNNING)
        await store.append(run.id, "Начало")
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False
    )
    session: AsyncSession
    async with sessions() as session, session.begin():
        interleaved: bool = False

        original: Callable[[Select[MessageRow, RunRow]], Awaitable[Result[MessageRow, RunRow]]] = (
            session.execute
        )

        async def execute(statement: Select[MessageRow, RunRow]) -> Result[MessageRow, RunRow]:
            nonlocal interleaved
            result: Result[MessageRow, RunRow] = await original(statement)
            if not interleaved and "FROM messages" in str(statement):
                interleaved = True
                writer: ChatStore
                async with stores.open() as writer:
                    await writer.append(run.id, " и конец")
                    await writer.set_status(run.id, RunStatus.COMPLETED)
            return result

        monkeypatch.setattr(session, "execute", execute)
        snapshot: ChatSnapshot = await SqlAlchemyStore(session).queries.snapshot(chat.id)
        assert interleaved
        answer: MessageView = snapshot.messages[-1]
        view: RunView = snapshot.runs[-1]
        assert view.content == answer.content
        assert view.incomplete == answer.incomplete
        if view.status == RunStatus.COMPLETED:
            assert answer.content == "Начало и конец"


@contextmanager
def record_selects(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def test_pending_fetches_all_runs_in_one_statement(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    created: list[RunView] = []
    index: int
    async with stores.open() as store:
        for index in range(2):
            chat: ChatView = await store.create_chat(f"Pending {index}")
            created.append(
                await store.start(
                    chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
                )
            )
    statements: list[str]
    with record_selects(engine) as statements:
        async with stores.open() as store:
            pending: list[PendingRun] = await store.queries.pending()
    assert {run.id for run in created} == {run.id for run in pending}
    assert len(statements) == 1
    assert "messages" not in statements[0].lower()
    run: RunView
    async with stores.open() as store:
        for run in created:
            await store.set_status(run.id, RunStatus.FAILED)


async def test_preference_reads_do_not_lock_and_writes_are_explicit(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    statements: list[str]
    with record_selects(engine) as statements:
        async with stores.open() as store:
            before: Preferences = await store.queries.preferences()
    assert all("FOR UPDATE" not in statement for statement in statements)
    async with stores.open() as store:
        await store.update_preferences(Preferences(theme="dark"))
    async with stores.open() as store:
        assert (await store.queries.preferences()).theme == "dark"
        await store.update_preferences(before)


async def test_task_scope_applies_to_creating_listing_and_loading_chat(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    async with stores.open() as store:
        local: ChatView = await store.create_chat("Local task")
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False
    )
    session: AsyncSession
    async with sessions() as session, session.begin():
        task: TaskRow | None = await session.scalar(select(TaskRow))
        assert task is not None
        task_id: UUID = uuid4()
        session.add(TaskRow(id=task_id, project_id=task.project_id, title="Other task"))
        await session.flush()
        scoped: SqlAlchemyStore = SqlAlchemyStore(session, task_id=task_id)
        other: ChatView = await scoped.create_chat("Scoped chat")
        assert other.task_id == task_id
        assert [chat.id for chat in await scoped.queries.list_chats()] == [other.id]
        with pytest.raises(Missing):
            await scoped.queries.snapshot(local.id)
        assert (await scoped.queries.snapshot(other.id)).chat.id == other.id
        with pytest.raises(Missing):
            await SqlAlchemyStore(session).queries.snapshot(other.id)


async def test_assistant_message_cannot_belong_to_two_runs(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    async with stores.open() as store:
        chat: ChatView = await store.create_chat("Unique answer")
        run: RunView = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
        await store.set_status(run.id, RunStatus.FAILED)
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False
    )
    session: AsyncSession
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
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    engine: AsyncEngine = resources[1]
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False
    )
    session: AsyncSession
    async with sessions() as session:
        await SqlAlchemyStore(session).queries.ready()
        await session.execute(text("UPDATE alembic_version SET version_num = '0001_chat'"))
        with pytest.raises(StorageUnavailable, match="schema"):
            await SqlAlchemyStore(session).queries.ready()
        await session.rollback()


async def test_status_write_uses_loaded_rows_and_keeps_cancel_precedence(
    resources: tuple[StoreContext[ChatStore], AsyncEngine],
) -> None:
    stores: StoreContext[ChatStore]
    engine: AsyncEngine
    stores, engine = resources
    store: ChatStore
    async with stores.open() as store:
        chat: ChatView = await store.create_chat("Loaded rows")
        run: RunView = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Вопрос"), "fake", "x"
        )
    statements: list[str]
    with record_selects(engine) as statements:
        async with stores.open() as store:
            claimed: RunView = await store.set_status(run.id, RunStatus.RUNNING)
    assert claimed.status == RunStatus.RUNNING
    assert len(statements) == 2
    async with stores.open() as store:
        await store.append(run.id, "Частичный ответ")
        cancelling: RunView = await store.set_status(run.id, RunStatus.CANCELLING)
        late: RunView = await store.set_status(run.id, RunStatus.COMPLETED)
        assert late == cancelling
        cancelled: RunView = await store.set_status(run.id, RunStatus.CANCELLED)
        assert cancelled.content == "Частичный ответ"
        assert cancelled.incomplete

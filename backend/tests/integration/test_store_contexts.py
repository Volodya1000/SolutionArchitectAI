import asyncio
import os
from collections.abc import AsyncIterator
from typing import Final, Literal
from uuid import uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.tests.integration.test_lifecycle import checked_out
from solution_architect_ai.application.errors.chat_errors import Missing, StorageUnavailable
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.chat_dto import ChatView
from solution_architect_ai.application.protocols.chat_protocols import ChatStore
from solution_architect_ai.application.protocols.clarification_protocols import ClarificationStore
from solution_architect_ai.application.protocols.discussion_protocols import DiscussionStore
from solution_architect_ai.application.protocols.document_protocols import DocumentStore
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.discussions import DiscussionProvider
from solution_architect_ai.di.documents import DocumentProvider
from solution_architect_ai.di.extraction import ExtractionProvider
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.persistence.models import ChatRow
from solution_architect_ai.persistence.store import SqlAlchemyStore
from solution_architect_ai.persistence.store_context import (
    SqlAlchemyStoreContext,
    SqlStoreErrorPolicy,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture(name="store_container")
async def store_container_fixture() -> AsyncIterator[AsyncContainer]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    container: AsyncContainer = make_async_container(
        AppProvider(),
        DocumentProvider(),
        ExtractionProvider(),
        DiscussionProvider(),
        context={Settings: bootstrap()},
    )
    try:
        yield container
    finally:
        await container.close()


async def test_dishka_resolves_five_store_specializations_with_one_sessionmaker(
    store_container: AsyncContainer,
) -> None:
    chats: StoreContext[ChatStore] = await store_container.get(StoreContext[ChatStore])
    documents: StoreContext[DocumentStore] = await store_container.get(StoreContext[DocumentStore])
    extractions: StoreContext[ExtractionStore] = await store_container.get(
        StoreContext[ExtractionStore]
    )
    clarifications: StoreContext[ClarificationStore] = await store_container.get(
        StoreContext[ClarificationStore]
    )
    discussions: StoreContext[DiscussionStore] = await store_container.get(
        StoreContext[DiscussionStore]
    )
    sessions: async_sessionmaker[AsyncSession] = await store_container.get(
        async_sessionmaker[AsyncSession]
    )
    contexts: tuple[StoreContext[object], ...] = (
        chats,
        documents,
        extractions,
        clarifications,
        discussions,
    )
    context: StoreContext[object]
    for context in contexts:
        assert isinstance(context, SqlAlchemyStoreContext)
        assert context.database_sessions is sessions
    chat_store: ChatStore
    async with chats.open() as chat_store:
        chat: ChatView = await chat_store.create_chat("Один общий источник сессий")
    async with chats.open() as chat_store:
        assert (await chat_store.queries.snapshot(chat.id)).chat.id == chat.id
    document_store: DocumentStore
    async with documents.open() as document_store:
        await document_store.list_documents()
    extraction_store: ExtractionStore
    async with extractions.open() as extraction_store:
        await extraction_store.list_runs()
    clarification_store: ClarificationStore
    with pytest.raises(Missing):
        async with clarifications.open() as clarification_store:
            await clarification_store.get(uuid4())
    discussion_store: DiscussionStore
    with pytest.raises(Missing):
        async with discussions.open() as discussion_store:
            await discussion_store.operation(uuid4())


@pytest.mark.parametrize("policy_name", ["STORAGE", "DOCUMENT", "EXTRACTION"])
async def test_validation_translation_rolls_back_without_changing_other_error_types(
    store_container: AsyncContainer, policy_name: Literal["STORAGE", "DOCUMENT", "EXTRACTION"]
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await store_container.get(
        async_sessionmaker[AsyncSession]
    )
    context: SqlAlchemyStoreContext[SqlAlchemyStore] = SqlAlchemyStoreContext(
        sessions, SqlAlchemyStore, SqlStoreErrorPolicy[policy_name]
    )
    title: str = f"Откат {uuid4()}"
    expected: type[Exception] = {
        "STORAGE": ValidationError,
        "DOCUMENT": DocumentFailure,
        "EXTRACTION": StoredExtractionCorrupt,
    }[policy_name]

    async def write_invalid_value() -> None:
        chat_store: SqlAlchemyStore
        async with context.open() as chat_store:
            await chat_store.create_chat(title)
            TypeAdapter(int).validate_python("invalid")

    with pytest.raises(expected):
        await write_invalid_value()
    session: AsyncSession
    async with sessions() as session:
        assert await session.scalar(select(ChatRow.id).where(ChatRow.title == title)) is None


async def test_five_second_timeout_rolls_back_and_translates_database_failure(
    store_container: AsyncContainer,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await store_container.get(
        async_sessionmaker[AsyncSession]
    )
    context: SqlAlchemyStoreContext[SqlAlchemyStore] = SqlAlchemyStoreContext(
        sessions, SqlAlchemyStore
    )
    title: str = f"Истекла транзакция {uuid4()}"

    async def write_until_timeout() -> None:
        chat_store: SqlAlchemyStore
        async with context.open() as chat_store:
            await chat_store.create_chat(title)
            await chat_store.session.execute(text("SELECT pg_sleep(10)"))

    with pytest.raises(StorageUnavailable):
        await write_until_timeout()
    session: AsyncSession
    async with sessions() as session:
        assert await session.scalar(select(ChatRow.id).where(ChatRow.title == title)) is None


async def test_cancellation_propagates_and_rolls_back_the_shared_scope(
    store_container: AsyncContainer,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await store_container.get(
        async_sessionmaker[AsyncSession]
    )
    context: SqlAlchemyStoreContext[SqlAlchemyStore] = SqlAlchemyStoreContext(
        sessions, SqlAlchemyStore
    )
    entered: asyncio.Event = asyncio.Event()
    title: str = f"Отменена транзакция {uuid4()}"

    async def write_until_cancelled() -> None:
        chat_store: SqlAlchemyStore
        async with context.open() as chat_store:
            await chat_store.create_chat(title)
            entered.set()
            await asyncio.Event().wait()

    task: asyncio.Task[None] = asyncio.create_task(write_until_cancelled())
    async with asyncio.timeout(3):
        await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    session: AsyncSession
    async with sessions() as session:
        assert await session.scalar(select(ChatRow.id).where(ChatRow.title == title)) is None
    engine: AsyncEngine = await store_container.get(AsyncEngine)
    assert checked_out(engine) == 0

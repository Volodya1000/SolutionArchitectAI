from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.extraction_resources import ExtractionResources
from solution_architect_ai.application.models.chat_dto import ChatView, Preferences, StartRun
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("scenario", ["first", "second"])
async def test_each_case_starts_with_seed_preferences_and_no_unrelated_pending_work(
    resources: ExtractionResources,
    scenario: str,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        store: SqlAlchemyStore = SqlAlchemyStore(session)
        assert (await store.queries.preferences()).theme == "system"
        assert await store.queries.pending() == []
        await store.update_preferences(Preferences(theme="dark"))
        chat: ChatView = await store.create_chat(scenario)
        await store.start(chat.id, StartRun(command_id=uuid4(), content="Pending"), "fake", "test")
    # Intentionally leave committed work/preferences: another test must not inherit them.
    async with sessions.begin() as session:
        store = SqlAlchemyStore(session)
        assert (await store.queries.preferences()).theme == "dark"
        assert len(await store.queries.pending()) == 1

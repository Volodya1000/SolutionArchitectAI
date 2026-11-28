from typing import Final
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.extraction_resources import ExtractionResources, upload
from solution_architect_ai.application.errors.chat_errors import StoredDataCorrupt
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.chat_dto import ChatView, Preferences, StartRun
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.application.models.structured_models import BudgetUsage
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.discussions.models import DiscussionOperationRow
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.models import PreferenceRow, RunRow
from solution_architect_ai.persistence.queries import Queries
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def test_corrupt_discussion_replay_is_not_database_unavailability(
    resources: ExtractionResources,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    actor: ActorContext = await resources.container.get(ActorContext)
    operation_id: UUID = uuid4()
    session: AsyncSession
    async with sessions.begin() as session:
        session.add(
            DiscussionOperationRow(
                task_id=actor.task_id,
                operation_id=operation_id,
                author_id=actor.id,
                command_json="{}",
                result_json="{}",
            )
        )
    async with sessions.begin() as session:
        with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
            await SqlAlchemyDiscussionStore(session, actor).operation(operation_id)
    async with sessions.begin() as session:
        row: DiscussionOperationRow | None = await session.get(
            DiscussionOperationRow, (actor.task_id, operation_id)
        )
        assert row is not None
        assert row.result_json == "{}"


async def test_corrupt_saved_preferences_are_not_database_unavailability(
    resources: ExtractionResources,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        await session.execute(update(PreferenceRow).values(theme="invalid"))
    async with sessions.begin() as session:
        with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
            await Queries(session).preferences()


async def test_corrupt_saved_chat_status_rolls_back_without_changing_the_row(
    resources: ExtractionResources,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        store: SqlAlchemyStore = SqlAlchemyStore(session)
        chat: ChatView = await store.create_chat("Corrupt status")
        run_id: UUID = (
            await store.start(
                chat.id, StartRun(command_id=uuid4(), content="Hello"), "fake-chat", "test"
            )
        ).id
        await session.execute(update(RunRow).where(RunRow.id == run_id).values(status="broken"))
    with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
        async with sessions.begin() as session:
            await SqlAlchemyStore(session).set_status(run_id, RunStatus.RUNNING)
    async with sessions.begin() as session:
        assert await session.scalar(select(RunRow.status).where(RunRow.id == run_id)) == "broken"


async def test_corrupt_extraction_status_does_not_spend_reserved_budget(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    session: AsyncSession
    async with sessions.begin() as session:
        await session.execute(
            update(ExtractionRow).where(ExtractionRow.id == run.id).values(status="broken")
        )
    with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
        async with sessions.begin() as session:
            await SqlAlchemyExtractionStore(session).reserve(run.id, BudgetUsage(1, 0, 0), 0)
    async with sessions.begin() as session:
        assert (
            await session.scalar(select(ExtractionRow.requests).where(ExtractionRow.id == run.id))
            == 0
        )
        # Resource teardown must still be able to read its deliberately corrupted run.
        await session.execute(
            update(ExtractionRow).where(ExtractionRow.id == run.id).values(status="queued")
        )


async def test_invalid_incoming_preferences_are_not_stored_corruption_or_a_durable_write(
    resources: ExtractionResources,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await resources.container.get(
        async_sessionmaker[AsyncSession]
    )
    value: Preferences = Preferences()
    # Exercise a DTO changed by a caller after its original validation.
    value.__dict__["theme"] = "invalid"
    session: AsyncSession
    with pytest.raises(ValidationError):
        async with sessions.begin() as session:
            await SqlAlchemyStore(session).update_preferences(value)
    async with sessions.begin() as session:
        assert (await Queries(session).preferences()).theme == "system"

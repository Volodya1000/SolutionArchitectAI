from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Nullable, Result, Row, ScalarResult, Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.chat_errors import (
    Missing,
    StorageUnavailable,
    StoredDataCorrupt,
)
from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    ChatView,
    MessageView,
    PendingRun,
    Preferences,
    RunView,
)
from solution_architect_ai.domain.runs import ACTIVE_STATUSES
from solution_architect_ai.persistence.models import ChatRow, MessageRow, PreferenceRow, RunRow
from solution_architect_ai.persistence.schema import migration_heads
from solution_architect_ai.persistence.stored_data import read_stored_model

DEFAULT_TASK_ID: Final[UUID] = UUID("10000000-0000-4000-8000-000000000002")


def run_view(row: RunRow, message: MessageRow) -> RunView:
    return read_stored_model(
        RunView,
        {
            "id": row.id,
            "chat_id": row.chat_id,
            "assistant_message_id": message.id,
            "status": row.status,
            "sequence": row.sequence,
            "content": message.content,
            "incomplete": row.incomplete,
            "error_code": row.error_code,
            "model": row.model,
            "config_digest": row.config_digest,
            "created_at": row.created_at,
        },
        failure=StoredDataCorrupt("stored_data_corrupt"),
    )


class Queries:
    def __init__(self, session: AsyncSession, *, task_id: UUID = DEFAULT_TASK_ID) -> None:
        self.session: AsyncSession = session
        self.task_id: UUID = task_id

    async def list_chats(self) -> list[ChatView]:
        rows: ScalarResult[ChatRow] = await self.session.scalars(
            select(ChatRow)
            .where(ChatRow.task_id == self.task_id)
            .order_by(ChatRow.created_at.desc())
        )
        return [
            read_stored_model(ChatView, row, failure=StoredDataCorrupt("stored_data_corrupt"))
            for row in rows
        ]

    async def chat_row(self, chat_id: UUID, *, lock: bool = False) -> ChatRow:
        """Load a persistence entity; writers lock the chat before allocating positions."""
        query: Select[ChatRow] = select(ChatRow).where(
            ChatRow.id == chat_id, ChatRow.task_id == self.task_id
        )
        row: ChatRow | None = await self.session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise Missing("chat")
        return row

    async def get_run(self, run_id: UUID) -> RunView:
        result: Result[RunRow, MessageRow] = await self.session.execute(
            select(RunRow, MessageRow)
            .join(MessageRow, MessageRow.id == RunRow.assistant_message_id)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(RunRow.id == run_id, ChatRow.task_id == self.task_id)
            .execution_options(populate_existing=True)
        )
        pair: Row[RunRow, MessageRow] | None = result.one_or_none()
        if pair is None:
            raise Missing("run")
        return run_view(*pair)

    async def snapshot(self, chat_id: UUID) -> ChatSnapshot:
        chat: ChatRow = await self.chat_row(chat_id)
        result: Result[MessageRow, RunRow | None] = await self.session.execute(
            select(MessageRow, Nullable(RunRow))
            .outerjoin(RunRow, RunRow.assistant_message_id == MessageRow.id)
            .where(MessageRow.chat_id == chat_id)
            .order_by(MessageRow.position)
            .execution_options(populate_existing=True)
        )
        pairs: Sequence[Row[MessageRow, RunRow | None]] = result.all()
        return ChatSnapshot(
            chat=read_stored_model(
                ChatView, chat, failure=StoredDataCorrupt("stored_data_corrupt")
            ),
            messages=[
                read_stored_model(
                    MessageView, message, failure=StoredDataCorrupt("stored_data_corrupt")
                )
                for message, _ in pairs
            ],
            runs=[run_view(run, message) for message, run in pairs if run is not None],
        )

    async def pending(self) -> list[PendingRun]:
        result: Result[UUID, str, datetime] = await self.session.execute(
            select(RunRow.id, RunRow.status, RunRow.created_at)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(RunRow.status.in_(ACTIVE_STATUSES), ChatRow.task_id == self.task_id)
            .order_by(RunRow.created_at, RunRow.id)
        )
        return [
            read_stored_model(PendingRun, row, failure=StoredDataCorrupt("stored_data_corrupt"))
            for row in result
        ]

    async def preferences(self) -> Preferences:
        row: PreferenceRow | None = await self.session.get(PreferenceRow, 1)
        if row is None:
            raise Missing("preferences")
        return read_stored_model(Preferences, row, failure=StoredDataCorrupt("stored_data_corrupt"))

    async def ready(self) -> None:
        versions: ScalarResult[str] = await self.session.scalars(
            text("SELECT version_num FROM alembic_version")
        )
        if frozenset(versions) != migration_heads():
            raise StorageUnavailable("schema_not_current")

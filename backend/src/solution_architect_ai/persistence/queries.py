from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.contracts import (
    ChatSnapshot,
    ChatView,
    MessageView,
    Missing,
    Preferences,
    RunView,
)
from solution_architect_ai.persistence.models import ChatRow, MessageRow, PreferenceRow, RunRow

TASK_ID = UUID("10000000-0000-4000-8000-000000000002")


class Queries:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_chats(self) -> list[ChatView]:
        rows = await self.session.scalars(
            select(ChatRow).where(ChatRow.task_id == TASK_ID).order_by(ChatRow.created_at.desc())
        )
        return [ChatView.model_validate(row) for row in rows]

    async def chat(self, chat_id: UUID, *, lock: bool = False) -> ChatRow:
        query = select(ChatRow).where(ChatRow.id == chat_id, ChatRow.task_id == TASK_ID)
        row = await self.session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise Missing("chat")
        return row

    async def get_run(self, run_id: UUID) -> RunView:
        row = await self.session.get(RunRow, run_id)
        if row is None:
            raise Missing("run")
        message = await self.session.get(MessageRow, row.assistant_message_id)
        if message is None:
            raise Missing("message")
        return RunView(
            id=row.id,
            chat_id=row.chat_id,
            assistant_message_id=message.id,
            status=row.status,
            sequence=row.sequence,
            content=message.content,
            incomplete=row.incomplete,
            error_code=row.error_code,
            model=row.model,
            config_digest=row.config_digest,
            created_at=row.created_at,
        )

    async def snapshot(self, chat_id: UUID) -> ChatSnapshot:
        chat = await self.chat(chat_id)
        messages = await self.session.scalars(
            select(MessageRow).where(MessageRow.chat_id == chat_id).order_by(MessageRow.position)
        )
        runs = await self.session.scalars(select(RunRow.id).where(RunRow.chat_id == chat_id))
        return ChatSnapshot(
            chat=ChatView.model_validate(chat),
            messages=[MessageView.model_validate(row) for row in messages],
            runs=[await self.get_run(run_id) for run_id in runs],
        )

    async def pending(self) -> list[RunView]:
        ids = await self.session.scalars(
            select(RunRow.id).where(RunRow.status.in_(["queued", "running", "cancelling"]))
        )
        return [await self.get_run(run_id) for run_id in ids]

    async def preferences(self, value: Preferences | None = None) -> Preferences:
        row = await self.session.get(PreferenceRow, 1, with_for_update=True)
        if row is None:
            raise Missing("preferences")
        if value is not None:
            row.theme = value.theme
        return Preferences(theme=row.theme)

    async def ready(self) -> None:
        version = await self.session.scalar(text("SELECT version_num FROM alembic_version"))
        if version != "0002_profile":
            raise Missing("schema")

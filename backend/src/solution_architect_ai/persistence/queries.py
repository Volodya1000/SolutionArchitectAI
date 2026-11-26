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
    StorageUnavailable,
)
from solution_architect_ai.persistence.models import ChatRow, MessageRow, PreferenceRow, RunRow
from solution_architect_ai.persistence.schema import migration_heads

DEFAULT_TASK_ID = UUID("10000000-0000-4000-8000-000000000002")


class Queries:
    def __init__(self, session: AsyncSession, *, task_id: UUID = DEFAULT_TASK_ID) -> None:
        self.session = session
        self.task_id = task_id

    async def list_chats(self) -> list[ChatView]:
        rows = await self.session.scalars(
            select(ChatRow)
            .where(ChatRow.task_id == self.task_id)
            .order_by(ChatRow.created_at.desc())
        )
        return [ChatView.model_validate(row) for row in rows]

    async def chat_row(self, chat_id: UUID, *, lock: bool = False) -> ChatRow:
        """Load a persistence entity; writers lock the chat before allocating positions."""
        query = select(ChatRow).where(ChatRow.id == chat_id, ChatRow.task_id == self.task_id)
        row = await self.session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise Missing("chat")
        return row

    async def get_run(self, run_id: UUID) -> RunView:
        result = await self.session.execute(
            select(RunRow, MessageRow)
            .join(MessageRow, MessageRow.id == RunRow.assistant_message_id)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(RunRow.id == run_id, ChatRow.task_id == self.task_id)
            .execution_options(populate_existing=True)
        )
        pair = result.one_or_none()
        if pair is None:
            raise Missing("run")
        return self.run_view(*pair)

    @staticmethod
    def run_view(row: RunRow, message: MessageRow) -> RunView:
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
        chat = await self.chat_row(chat_id)
        result = await self.session.execute(
            select(MessageRow, RunRow)
            .outerjoin(RunRow, RunRow.assistant_message_id == MessageRow.id)
            .where(MessageRow.chat_id == chat_id)
            .order_by(MessageRow.position)
            .execution_options(populate_existing=True)
        )
        pairs = result.all()
        return ChatSnapshot(
            chat=ChatView.model_validate(chat),
            messages=[MessageView.model_validate(message) for message, _ in pairs],
            runs=[self.run_view(run, message) for message, run in pairs if run is not None],
        )

    async def pending(self) -> list[RunView]:
        result = await self.session.execute(
            select(RunRow, MessageRow)
            .join(MessageRow, MessageRow.id == RunRow.assistant_message_id)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(
                RunRow.status.in_(["queued", "running", "cancelling"]),
                ChatRow.task_id == self.task_id,
            )
            .order_by(RunRow.created_at, RunRow.id)
            .execution_options(populate_existing=True)
        )
        return [self.run_view(run, message) for run, message in result.all()]

    async def preferences(self) -> Preferences:
        row = await self.session.get(PreferenceRow, 1)
        if row is None:
            raise Missing("preferences")
        return Preferences(theme=row.theme)

    async def ready(self) -> None:
        versions = await self.session.scalars(text("SELECT version_num FROM alembic_version"))
        if frozenset(versions) != migration_heads():
            raise StorageUnavailable("schema_not_current")

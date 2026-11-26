from uuid import UUID

from sqlalchemy import Result, func, or_, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.dto import (
    ChatView,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.application.errors import Conflict, Missing
from solution_architect_ai.domain.commands import (
    StartCandidate,
    content_digest,
    message_positions,
    replay_run,
)
from solution_architect_ai.domain.errors import StartConflict
from solution_architect_ai.domain.runs import (
    ACTIVE_STATUSES,
    RunErrorCode,
    RunStatus,
    resolve_transition,
)
from solution_architect_ai.persistence.models import ChatRow, MessageRow, PreferenceRow, RunRow
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID, Queries, run_view


class SqlAlchemyStore:
    def __init__(self, session: AsyncSession, *, task_id: UUID = DEFAULT_TASK_ID) -> None:
        self.session: AsyncSession = session
        self.queries: Queries = Queries(session, task_id=task_id)

    async def create_chat(self, title: str) -> ChatView:
        row: ChatRow = ChatRow(task_id=self.queries.task_id, title=title)
        self.session.add(row)
        await self.session.flush()
        return ChatView.model_validate(row)

    async def start(self, chat_id: UUID, command: StartRun, model: str, digest: str) -> RunView:
        await self.queries.chat_row(chat_id, lock=True)
        payload_digest: str = content_digest(command.content)
        existing: UUID | None = await self.replay(chat_id, command.command_id, payload_digest)
        if existing is not None:
            return await self.queries.get_run(existing)
        last_position: int | None = await self.session.scalar(
            select(func.max(MessageRow.position)).where(MessageRow.chat_id == chat_id)
        )
        user_position: int
        assistant_position: int
        user_position, assistant_position = message_positions(last_position)
        user: MessageRow = MessageRow(
            chat_id=chat_id, role="user", content=command.content, position=user_position
        )
        assistant: MessageRow = MessageRow(
            chat_id=chat_id, role="assistant", position=assistant_position, incomplete=True
        )
        self.session.add_all([user, assistant])
        await self.session.flush()
        run: RunRow = RunRow(
            chat_id=chat_id,
            command_id=command.command_id,
            payload_digest=payload_digest,
            assistant_message_id=assistant.id,
            model=model,
            config_digest=digest,
        )
        self.session.add(run)
        await self.session.flush()
        return run_view(run, assistant)

    async def replay(self, chat_id: UUID, command_id: UUID, payload_digest: str) -> UUID | None:
        result: Result[UUID, UUID, str] = await self.session.execute(
            select(RunRow.id, RunRow.command_id, RunRow.payload_digest).where(
                RunRow.chat_id == chat_id,
                or_(RunRow.command_id == command_id, RunRow.status.in_(ACTIVE_STATUSES)),
            )
        )
        candidates: list[StartCandidate] = [StartCandidate(*row) for row in result]
        try:
            return replay_run(command_id, payload_digest, candidates)
        except StartConflict as conflict:
            raise Conflict(conflict.reason) from conflict

    async def locked_run(self, run_id: UUID) -> RunRow:
        row: RunRow | None = await self.session.scalar(
            select(RunRow)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(RunRow.id == run_id, ChatRow.task_id == self.queries.task_id)
            .with_for_update(of=RunRow)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise Missing("run")
        return row

    async def set_status(
        self, run_id: UUID, target: RunStatus, error: RunErrorCode | None = None
    ) -> RunView:
        row: RunRow = await self.locked_run(run_id)
        status: RunStatus = RunStatus(row.status)
        resolved: RunStatus = resolve_transition(status, target, error)
        message: MessageRow = await self.assistant_message(row)
        if resolved == status:
            return run_view(row, message)
        row.status = resolved.value
        row.sequence += 1
        row.error_code = error
        row.incomplete = target != RunStatus.COMPLETED
        message.incomplete = row.incomplete
        await self.session.flush()
        return run_view(row, message)

    async def assistant_message(self, row: RunRow) -> MessageRow:
        # All answer writers first hold this run's lock; refresh a previously read entity.
        message: MessageRow | None = await self.session.get(
            MessageRow, row.assistant_message_id, populate_existing=True
        )
        if message is None:
            raise Missing("message")
        return message

    async def append(self, run_id: UUID, text: str) -> bool:
        # PostgreSQL locks/rechecks the run before its RETURNING row can drive the
        # answer update. Each streamed delta becomes durable in one statement.
        answer_id: UUID | None = await self.session.scalar(
            sql_text("""
                WITH claimed AS (
                    UPDATE runs SET sequence = runs.sequence + 1
                    FROM chats
                    WHERE runs.id = :run_id AND runs.status = :running
                      AND chats.id = runs.chat_id AND chats.task_id = :task_id
                    RETURNING runs.assistant_message_id
                )
                UPDATE messages SET content = messages.content || :delta
                FROM claimed WHERE messages.id = claimed.assistant_message_id
                RETURNING messages.id
            """),
            {
                "run_id": run_id,
                "running": RunStatus.RUNNING.value,
                "task_id": self.queries.task_id,
                "delta": text,
            },
        )
        if answer_id is not None:
            return True
        # A stopped run is a cancellation signal. Preserve the distinct missing-run
        # error (including task scope) on the uncommon unsuccessful path.
        await self.locked_run(run_id)
        return False

    async def update_preferences(self, value: Preferences) -> Preferences:
        row: PreferenceRow | None = await self.session.get(
            PreferenceRow, 1, with_for_update=True, populate_existing=True
        )
        if row is None:
            raise Missing("preferences")
        row.theme = value.theme
        await self.session.flush()
        return Preferences(theme=row.theme)

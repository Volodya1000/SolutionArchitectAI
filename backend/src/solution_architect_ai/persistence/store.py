from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select

from solution_architect_ai.application.contracts import (
    ChatView,
    Conflict,
    Missing,
    Preferences,
    RunView,
    StartRun,
)
from solution_architect_ai.domain.runs import RunStatus, resolve_transition
from solution_architect_ai.persistence.models import ChatRow, MessageRow, PreferenceRow, RunRow
from solution_architect_ai.persistence.queries import Queries


class SqlAlchemyStore(Queries):
    async def create_chat(self, title: str) -> ChatView:
        row = ChatRow(task_id=self.task_id, title=title)
        self.session.add(row)
        await self.session.flush()
        return ChatView.model_validate(row)

    async def start(self, chat_id: UUID, command: StartRun, model: str, digest: str) -> RunView:
        await self.chat_row(chat_id, lock=True)
        payload_digest = sha256(command.content.encode()).hexdigest()
        old = await self.session.scalar(
            select(RunRow).where(
                RunRow.chat_id == chat_id,
                RunRow.command_id == command.command_id,
            )
        )
        if old is not None:
            if old.payload_digest != payload_digest:
                raise Conflict("command_payload_conflict")
            return await self.get_run(old.id)
        active = await self.session.scalar(
            select(RunRow.id).where(
                RunRow.chat_id == chat_id,
                RunRow.status.in_(["queued", "running", "cancelling"]),
            )
        )
        if active is not None:
            raise Conflict("chat_has_active_run")
        position = await self.session.scalar(
            select(func.coalesce(func.max(MessageRow.position), 0)).where(
                MessageRow.chat_id == chat_id
            )
        )
        position = int(position or 0)
        user = MessageRow(
            chat_id=chat_id, role="user", content=command.content, position=position + 1
        )
        assistant = MessageRow(
            chat_id=chat_id, role="assistant", position=position + 2, incomplete=True
        )
        self.session.add_all([user, assistant])
        await self.session.flush()
        run = RunRow(
            chat_id=chat_id,
            command_id=command.command_id,
            payload_digest=payload_digest,
            assistant_message_id=assistant.id,
            model=model,
            config_digest=digest,
        )
        self.session.add(run)
        await self.session.flush()
        return self.run_view(run, assistant)

    async def locked_run(self, run_id: UUID) -> RunRow:
        row = await self.session.scalar(
            select(RunRow)
            .join(ChatRow, ChatRow.id == RunRow.chat_id)
            .where(RunRow.id == run_id, ChatRow.task_id == self.task_id)
            .with_for_update(of=RunRow)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise Missing("run")
        return row

    async def set_status(
        self, run_id: UUID, target: RunStatus, error: str | None = None
    ) -> RunView:
        row = await self.locked_run(run_id)
        status = RunStatus(row.status)
        resolved = resolve_transition(status, target, error)
        message = await self.assistant_message(row)
        if resolved == status:
            return self.run_view(row, message)
        row.status = resolved.value
        row.sequence += 1
        row.error_code = error
        row.incomplete = target != RunStatus.COMPLETED
        message.incomplete = row.incomplete
        await self.session.flush()
        return self.run_view(row, message)

    async def assistant_message(self, row: RunRow) -> MessageRow:
        # All answer writers first hold this run's lock; refresh a previously read entity.
        message = await self.session.get(
            MessageRow, row.assistant_message_id, populate_existing=True
        )
        if message is None:
            raise Missing("message")
        return message

    async def append(self, run_id: UUID, text: str) -> bool:
        row = await self.locked_run(run_id)
        if row.status != RunStatus.RUNNING:
            return False
        message = await self.assistant_message(row)
        message.content += text
        row.sequence += 1
        await self.session.flush()
        return True

    async def update_preferences(self, value: Preferences) -> Preferences:
        row = await self.session.get(PreferenceRow, 1, with_for_update=True, populate_existing=True)
        if row is None:
            raise Missing("preferences")
        row.theme = value.theme
        await self.session.flush()
        return Preferences(theme=row.theme)

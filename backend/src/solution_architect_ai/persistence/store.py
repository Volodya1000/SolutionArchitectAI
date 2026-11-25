from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select

from solution_architect_ai.application.contracts import (
    ChatView,
    Conflict,
    Missing,
    RunView,
    StartRun,
)
from solution_architect_ai.domain.runs import RunStatus, transition
from solution_architect_ai.persistence.models import ChatRow, MessageRow, RunRow
from solution_architect_ai.persistence.queries import TASK_ID, Queries


class PostgresStore(Queries):
    async def create_chat(self, title: str) -> ChatView:
        row = ChatRow(task_id=TASK_ID, title=title)
        self.session.add(row)
        await self.session.flush()
        return ChatView.model_validate(row)

    async def start(self, chat_id: UUID, command: StartRun, model: str, digest: str) -> RunView:
        await self.chat(chat_id, lock=True)
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
        return await self.get_run(run.id)

    async def locked_run(self, run_id: UUID) -> RunRow:
        row = await self.session.scalar(
            select(RunRow)
            .where(RunRow.id == run_id)
            .with_for_update()
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
        if status.terminal or status == target:
            return await self.get_run(run_id)
        if target == RunStatus.RUNNING and status != RunStatus.QUEUED:
            return await self.get_run(run_id)
        if status == RunStatus.CANCELLING and target == RunStatus.COMPLETED:
            return await self.get_run(run_id)
        row.status = transition(status, target).value
        row.sequence += 1
        row.error_code = error
        row.incomplete = target != RunStatus.COMPLETED
        message = await self.session.get(MessageRow, row.assistant_message_id)
        if message is None:
            raise Missing("message")
        message.incomplete = row.incomplete
        await self.session.flush()
        return await self.get_run(run_id)

    async def append(self, run_id: UUID, text: str) -> bool:
        row = await self.locked_run(run_id)
        if row.status != RunStatus.RUNNING:
            return False
        message = await self.session.get(MessageRow, row.assistant_message_id)
        if message is None:
            raise Missing("message")
        message.content += text
        row.sequence += 1
        await self.session.flush()
        return True

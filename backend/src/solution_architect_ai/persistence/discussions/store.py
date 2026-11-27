from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.chat_errors import Conflict, Missing
from solution_architect_ai.application.errors.clarification_errors import PermissionDenied
from solution_architect_ai.application.models.chat_dto import ChatView
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.models.discussion_models import (
    CreateDiscussion,
    DiscussionBinding,
)
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.persistence.discussions.models import (
    DiscussionOperationRow,
    DiscussionRow,
)
from solution_architect_ai.persistence.documents.document_models import DocumentVersionRow
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.models import ChatRow, TaskRow


class SqlAlchemyDiscussionStore:
    def __init__(self, session: AsyncSession, actor: ActorContext) -> None:
        self.session: AsyncSession = session
        self.actor: ActorContext = actor

    async def analysis(self, run_id: UUID) -> ExtractionView:
        row: ExtractionRow | None = await self.session.scalar(
            select(ExtractionRow).where(
                ExtractionRow.id == run_id, ExtractionRow.task_id == self.actor.task_id
            )
        )
        if row is None:
            raise Missing("analysis")
        return ExtractionView.model_validate_json(row.snapshot_json)

    async def check_version(self, version_id: UUID) -> None:
        row: DocumentVersionRow | None = await self.session.scalar(
            select(DocumentVersionRow).where(
                DocumentVersionRow.version_id == version_id,
                DocumentVersionRow.task_id == self.actor.task_id,
            )
        )
        if row is None:
            raise Missing("source_version")

    async def replay(self, command: CreateDiscussion) -> ChatView | None:
        row: DiscussionOperationRow | None = await self.session.get(
            DiscussionOperationRow, (self.actor.task_id, command.operation_id)
        )
        if row is None:
            return None
        if row.author_id != self.actor.id:
            raise Missing("discussion_operation")
        if CreateDiscussion.model_validate_json(row.command_json) != command:
            raise Conflict("operation_payload_changed")
        return ChatView.model_validate_json(row.result_json)

    async def operation(self, operation_id: UUID) -> ChatView:
        row: DiscussionOperationRow | None = await self.session.get(
            DiscussionOperationRow, (self.actor.task_id, operation_id)
        )
        if row is None or row.author_id != self.actor.id:
            raise Missing("discussion_operation")
        return ChatView.model_validate_json(row.result_json)

    async def create(self, command: CreateDiscussion, binding: DiscussionBinding) -> ChatView:
        if not self.actor.can_write:
            raise PermissionDenied("permission_denied")
        # Serialize operation replay and insertion in one transaction, including a lost response.
        task: TaskRow | None = await self.session.scalar(
            select(TaskRow).where(TaskRow.id == self.actor.task_id).with_for_update()
        )
        if task is None:
            raise Missing("task")
        replay: ChatView | None = await self.replay(command)
        if replay is not None:
            return replay
        chat: ChatRow = ChatRow(
            id=binding.view.chat_id, task_id=self.actor.task_id, title=binding.view.title
        )
        self.session.add(chat)
        await self.session.flush()
        result: ChatView = ChatView.model_validate(chat)
        self.session.add(DiscussionRow(chat_id=chat.id, binding_json=binding.model_dump_json()))
        self.session.add(
            DiscussionOperationRow(
                task_id=self.actor.task_id,
                operation_id=command.operation_id,
                author_id=self.actor.id,
                command_json=command.model_dump_json(),
                result_json=result.model_dump_json(),
            )
        )
        await self.session.flush()
        return result

    async def get(self, chat_id: UUID) -> DiscussionBinding | None:
        chat: ChatRow | None = await self.session.scalar(
            select(ChatRow).where(ChatRow.id == chat_id, ChatRow.task_id == self.actor.task_id)
        )
        if chat is None:
            raise Missing("chat")
        row: DiscussionRow | None = await self.session.get(DiscussionRow, chat_id)
        return None if row is None else DiscussionBinding.model_validate_json(row.binding_json)

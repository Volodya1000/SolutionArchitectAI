import asyncio
import json
from typing import Final, Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.tests.integration.test_extraction_lifecycle import ExtractionResources, upload
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from solution_architect_ai.application.errors.chat_errors import Conflict, Missing
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionMatches,
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore
from solution_architect_ai.application.protocols.clarification_protocols import ClarificationStore
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
    QuestionRevisionRow,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.models import TaskRow
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("mode", ["reuse", "new"])
async def test_unavailable_history_is_rejected_before_queue_insertion(
    resources: ExtractionResources, mode: Literal["reuse", "new"]
) -> None:
    version: DocumentVersionView = await upload(resources)
    command: ExtractionStart = ExtractionStart.model_validate(
        {
            "operation_id": uuid4(),
            "version_ids": [version.version_id],
            "answer_history_mode": mode,
            "answer_history_id": uuid4(),
        }
    )
    expected_error: type[Missing] | type[Conflict] = Conflict if mode == "new" else Missing
    expected_code: str = "answer_history_selection_conflict" if mode == "new" else "answer_history"
    with pytest.raises(expected_error, match=expected_code):
        await resources.service.start(command)
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    async with engine.connect() as connection:
        assert (
            await connection.scalar(
                select(func.count())
                .select_from(ExtractionRow)
                .where(ExtractionRow.operation_id == command.operation_id)
            )
            == 0
        )


async def test_foreign_task_history_is_rejected_before_queue_insertion(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    history_run: ExtractionView = await resources.start([version.version_id])
    history_id: UUID = uuid4()
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    foreign_task: UUID = uuid4()
    async with engine.begin() as connection:
        project_id: UUID | None = await connection.scalar(
            select(TaskRow.project_id).where(TaskRow.id == DEFAULT_TASK_ID)
        )
        assert project_id is not None
        await connection.execute(
            insert(TaskRow).values(id=foreign_task, project_id=project_id, title="Другая задача")
        )
        # A history UUID alone is insufficient: its owning extraction belongs elsewhere.
        await connection.execute(
            update(ExtractionRow)
            .where(ExtractionRow.id == history_run.id)
            .values(task_id=foreign_task)
        )
        await connection.execute(
            insert(ClarificationRunRow).values(run_id=history_run.id, history_id=history_id)
        )
    resources.runs.remove(history_run.id)
    with pytest.raises(Missing, match="answer_history"):
        await resources.service.start(
            ExtractionStart(
                operation_id=uuid4(), version_ids=[version.version_id], answer_history_id=history_id
            )
        )


async def test_legacy_unavailable_history_fails_only_its_run(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[version.version_id], answer_history_id=uuid4()
    )
    async with engine.begin() as connection:
        await connection.execute(
            update(ExtractionRow)
            .where(ExtractionRow.id == run.id)
            .values(command_json=command.model_dump_json())
        )
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    chats: StoreContext[ChatStore] = await resources.container.get(StoreContext[ChatStore])

    async def create_sibling_chat() -> None:
        chat_store: ChatStore
        async with chats.open() as chat_store:
            await chat_store.create_chat("Соседний чат продолжает работать")

    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        group.create_task(worker.execute(run.id))
        group.create_task(create_sibling_chat())
    failed: ExtractionView = await resources.view(run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "answer_history_unavailable"


async def test_waiting_run_is_selectable_but_unanswered_run_is_not_scheduled(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    clarifications: StoreContext[ClarificationStore] = await resources.container.get(
        StoreContext[ClarificationStore]
    )
    clarification_store: ClarificationStore
    async with clarifications.open() as clarification_store:
        await clarification_store.save_questions(
            run.id,
            [
                ClarificationQuestion(
                    id=uuid4(),
                    gap_key=f"pending:{run.id}",
                    text="Как обработать отказ?",
                    basis="Нет политики отказа",
                    dependent_decision="Обработка отказа",
                    blocking=True,
                    requirement_ids=[uuid4()],
                    sources=[],
                )
            ],
        )
        await clarification_store.set_waiting(run.id)
    matches: ExtractionMatches = await resources.service.get_matching([version.version_id], "")
    assert matches.active is not None
    assert matches.active.id == run.id
    assert matches.active.status == RunStatus.WAITING_INPUT
    extraction_store: ExtractionStore
    async with resources.stores.open() as extraction_store:
        assert run.id not in {item.id for item in await extraction_store.pending()}


async def test_legacy_completed_duration_survives_clarification_read_and_both_getters(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    legacy: ExtractionView = run.model_copy(
        update={"status": RunStatus.COMPLETED, "elapsed_seconds": 42.5}
    )
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    async with engine.begin() as connection:
        await connection.execute(
            update(ExtractionRow)
            .where(ExtractionRow.id == run.id)
            .values(status="completed", snapshot_json=legacy.model_dump_json())
        )
        operation_id: UUID | None = await connection.scalar(
            select(ExtractionRow.operation_id).where(ExtractionRow.id == run.id)
        )
    assert operation_id is not None
    service: ClarificationService = await resources.container.get(ClarificationService)
    await service.get(run.id)
    assert (await resources.service.get(run.id)).elapsed_seconds == 42.5
    assert (await resources.service.get_operation(operation_id)).elapsed_seconds == 42.5


async def test_resume_intent_does_not_schedule_an_assumed_mandatory_conflict(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.service.start(
        ExtractionStart(
            operation_id=uuid4(), version_ids=[version.version_id], answer_history_mode="new"
        )
    )
    resources.runs.append(run.id)
    contexts: StoreContext[ClarificationStore] = await resources.container.get(
        StoreContext[ClarificationStore]
    )
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"mandatory:{run.id}",
        text="Как выполнить обязательное правило?",
        basis="Обязательное правило противоречит допущению",
        dependent_decision="Выполнение правила",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    store: ClarificationStore
    async with contexts.open() as store:
        await store.save_questions(run.id, [question])
        await store.set_waiting(run.id)
    snapshot: dict[str, object] = question.model_dump(mode="json")
    snapshot.update(status="assumed", mandatory_conflict="Обязательное правило запрещает допущение")
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    async with engine.begin() as connection:
        await connection.execute(
            update(QuestionRevisionRow)
            .where(QuestionRevisionRow.question_id == question.id)
            .values(status="assumed", snapshot_json=json.dumps(snapshot))
        )
        await connection.execute(
            update(ClarificationRunRow)
            .where(ClarificationRunRow.run_id == run.id)
            .values(resume_pending=True)
        )
    extraction_store: ExtractionStore
    async with resources.stores.open() as extraction_store:
        assert run.id not in {item.id for item in await extraction_store.pending()}

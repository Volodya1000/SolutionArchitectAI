import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
)
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    RequirementView,
    StoredModelProfile,
)
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow


async def seed_run(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    run_id: UUID,
    question: ClarificationQuestion,
) -> None:
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[uuid4()], answer_history_mode="new"
    )
    settings: Settings = bootstrap()
    view: ExtractionView = ExtractionView(
        id=run_id,
        status=RunStatus.WAITING_INPUT,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model="fake-chat",
        coverage=CoverageView(),
        model_profile=StoredModelProfile.model_validate(
            settings.llm.model_dump(mode="json", exclude={"api_key"})
        ),
        contract_version="test",
        prompt_version="test",
        requirements=[
            RequirementView(
                id=question.requirement_ids[0],
                category=RequirementCategory.FUNCTIONAL,
                original_text="Исходное требование",
                normalized_text="Исходное требование",
                sources=[],
            )
        ],
    )
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        store.session.add(
            ExtractionRow(
                id=run_id,
                task_id=stores.actor.task_id,
                operation_id=command.operation_id,
                payload_digest="test",
                config_digest="test",
                command_json=command.model_dump_json(),
                snapshot_json=view.model_dump_json(),
                status=view.status.value,
                created_at=view.created_at,
            )
        )
        await store.session.flush()
        await store.save_questions(run_id, [question])


async def wait_for_database_lock(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore], backend_pid: int
) -> None:
    monitor: SqlAlchemyClarificationStore
    async with stores.open() as monitor, asyncio.timeout(3):
        while True:
            waiting: bool | None = await monitor.session.scalar(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": backend_pid},
            )
            if waiting is True:
                return
            await asyncio.sleep(0.01)

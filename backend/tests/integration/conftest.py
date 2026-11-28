import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.test_helpers.clarification_http import HttpCase
from backend.test_helpers.discussion_resources import Resources
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.postgres_isolation import isolated_test_database
from backend.test_helpers.sql_store_setup import (
    SqlStoreSetup,
    clarification_store_setup,
    discussion_store_setup,
    document_store_setup,
)
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    ClarificationQuestion,
    ClarificationView,
)
from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
)
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractionStart,
    ExtractionView,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import ExecutionBudget
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStore,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.config.models import (
    GitSettings,
    LLMSettings,
    RetryConfig,
    StorageSettings,
)
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.documents import DocumentProvider
from solution_architect_ai.di.extraction import ExtractionProvider
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import AppProvider, database_url
from solution_architect_ai.domain.requirements import EvidenceStatus
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


@pytest.fixture(autouse=True)
async def isolated_postgres(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None]:
    if request.node.get_closest_marker("integration") is None:
        yield
        return
    async with isolated_test_database(bootstrap().database) as database:
        monkeypatch.setenv("SAA_DATABASE__DATABASE", database)
        yield


@pytest.fixture(name="resources")
async def extraction_resources(tmp_path: Path) -> AsyncGenerator[ExtractionResources]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    profile: LLMSettings = LLMSettings(
        base_url=os.environ["SAA_LLM__BASE_URL"],
        model="fake-chat",
        context_window=16000,
        output_limit=2048,
        approximate_chars_per_token=1,
        retry=RetryConfig(max_total_requests=128, deadline_seconds=120, request_timeout_seconds=30),
    )
    settings: Settings = Settings(
        config_root=tmp_path,
        mode="test",
        llm=profile,
        storage=StorageSettings(root=tmp_path / "files"),
        git=GitSettings(root=tmp_path / "git"),
    )
    container: AsyncContainer = make_async_container(
        AppProvider(), DocumentProvider(), ExtractionProvider(), context={Settings: settings}
    )
    resources: ExtractionResources = ExtractionResources(
        container,
        settings,
        await container.get(DocumentService),
        await container.get(StoreContext[ExtractionStore]),
        await container.get(RequirementsExtractionService),
        [],
    )
    try:
        yield resources
    finally:
        store: ExtractionStore
        async with resources.stores.open() as store:
            for run_id in resources.runs:
                if not (await store.get(run_id)).status.terminal:
                    await store.set_status(run_id, RunStatus.FAILED, "test_cleanup")
        await resources.container.close()


@pytest.fixture(name="decision_stores")
async def decision_stores_fixture() -> AsyncGenerator[SqlStoreSetup[SqlAlchemyClarificationStore]]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    settings: Settings = bootstrap()
    engine: AsyncEngine = create_async_engine(database_url(settings))
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield clarification_store_setup(sessions, ActorContext.local(DEFAULT_TASK_ID))
    finally:
        await engine.dispose()


@pytest.fixture(name="http_case")
async def http_case_fixture(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> HttpCase:
    agent: ClarificationAgent = await resources.container.get(ClarificationAgent)

    async def scripted_questions(
        context: ClarificationContext, _budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        fragment: ContextFragment = context.part.fragments[-1]
        source: SourceRef = verify_evidence(
            Evidence(fragment_id=str(fragment.fragment_id), quote=fragment.text), context.part
        )
        assert source.status == EvidenceStatus.VERIFIED
        return [
            ClarificationQuestion(
                id=uuid4(),
                gap_key=f"{fragment.file_id}:http-failure-policy",
                text="Как реагировать на отказ сохранения?",
                basis="Поведение при отказе не определено",
                dependent_decision="Обработка отказа сохранения",
                blocking=True,
                requirement_ids=[min(context.requirements, key=lambda item: item.original_text).id],
                sources=[source],
            )
        ]

    monkeypatch.setattr(agent, "clarify", scripted_questions)
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.service.start(
        ExtractionStart(
            operation_id=uuid4(), version_ids=[version.version_id], answer_history_mode="new"
        )
    )
    resources.runs.append(run.id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.WAITING_INPUT
    service: ClarificationService = await resources.container.get(ClarificationService)
    view: ClarificationView = await service.get(run.id)
    assert len(view.questions) == 1
    stores: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        await resources.container.get(async_sessionmaker[AsyncSession]),
        await resources.container.get(ActorContext),
    )
    return HttpCase(resources, service, stores, version, run.id, view.questions[0])


@pytest.fixture(name="discussion_resources")
async def discussion_resources(tmp_path: Path) -> AsyncGenerator[Resources]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    settings: Settings = bootstrap()
    engine: AsyncEngine = create_async_engine(database_url(settings))
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    actor: ActorContext = ActorContext.local(DEFAULT_TASK_ID)
    documents: DocumentService = DocumentService(
        document_store_setup(sessions), LocalFileStorage(tmp_path), DocumentParser()
    )
    clarifications: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        sessions, actor
    )
    stores: SqlStoreSetup[SqlAlchemyDiscussionStore] = discussion_store_setup(sessions, actor)
    try:
        yield Resources(
            DiscussionService(stores, documents, ClarificationService(clarifications, documents)),
            stores,
            clarifications,
            documents,
            tmp_path,
        )
    finally:
        await engine.dispose()

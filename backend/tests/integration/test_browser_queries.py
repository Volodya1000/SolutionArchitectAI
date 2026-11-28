import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, from_context, make_async_container
from dishka.dependency_source import CompositeDependencySource
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.test_helpers.sql_store_setup import document_store_setup, extraction_store_setup
from solution_architect_ai.application.errors.chat_errors import ChatError, Missing
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.document_dto import DocumentView, UploadDocument
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    StoredExtractionSummary,
    StoredModelProfile,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.di.main import bootstrap, chat_error
from solution_architect_ai.di.providers import database_url
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser
from solution_architect_ai.infrastructure.storage.local_files_storage import LocalFileStorage
from solution_architect_ai.persistence.documents.document_models import (
    DocumentRow,
    DocumentVersionRow,
)
from solution_architect_ai.persistence.documents.document_store import SqlAlchemyDocumentStore
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.models import ProjectRow, TaskRow
from solution_architect_ai.presentation.extraction_routes import router

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]
PROFILE: Final[StoredModelProfile] = StoredModelProfile.model_validate(
    LLMSettings().model_dump(mode="json", exclude={"api_key"})
)


class ServiceProvider(Provider):
    service: CompositeDependencySource = from_context(
        RequirementsExtractionService, scope=Scope.APP
    )


@pytest.fixture(name="browser_client")
async def browser_client_fixture(
    session: AsyncSession, tmp_path: Path
) -> AsyncIterator[tuple[httpx.AsyncClient, UUID]]:
    task_id: UUID = await create_task(session)
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
        await session.connection(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    documents: DocumentService = DocumentService(
        document_store_setup(sessions, task_id=task_id),
        LocalFileStorage(tmp_path, max_bytes=4096),
        DocumentParser(),
    )
    service: RequirementsExtractionService = RequirementsExtractionService(
        extraction_store_setup(sessions, task_id=task_id), documents, PROFILE, "config"
    )
    container: AsyncContainer = make_async_container(
        ServiceProvider(), context={RequirementsExtractionService: service}
    )
    app: FastAPI = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ChatError, chat_error)
    setup_dishka(container, app)
    try:
        client: httpx.AsyncClient
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, task_id
    finally:
        await container.close()


@pytest.fixture(name="session")
async def database_session_fixture() -> AsyncIterator[AsyncSession]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    engine: AsyncEngine = create_async_engine(database_url(bootstrap()))
    try:
        connection: AsyncConnection
        async with engine.connect() as connection, connection.begin():
            database_session: AsyncSession
            async with AsyncSession(connection, expire_on_commit=False) as database_session:
                yield database_session
            await connection.rollback()
    finally:
        await engine.dispose()


async def create_task(session: AsyncSession) -> UUID:
    project_id: UUID = uuid4()
    task_id: UUID = uuid4()
    session.add(ProjectRow(id=project_id, title="Browser query test"))
    await session.flush()
    session.add(TaskRow(id=task_id, project_id=project_id, title="Browser query test"))
    await session.flush()
    return task_id


def extraction_row(task_id: UUID, created_at: datetime) -> ExtractionRow:
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[uuid4()], analysis_scope="Current scope"
    )
    view: ExtractionView = ExtractionView(
        id=uuid4(),
        status=RunStatus.RUNNING,
        progress=ExtractionProgress(completed_parts=1, total_parts=3),
        error_code=None,
        created_at=created_at,
        model=PROFILE.model,
        model_profile=PROFILE,
        coverage=CoverageView(),
        requirements=[],
        contract_version=CONTRACT_VERSION,
        prompt_version=PROMPT_VERSION,
    )
    snapshot: dict[str, object] = json.loads(view.model_dump_json())
    # Summary reads must tolerate malformed result content; full detail must reject it.
    snapshot["requirements"] = [{"invalid_result": "x" * 10000}]
    return ExtractionRow(
        id=view.id,
        task_id=task_id,
        operation_id=command.operation_id,
        payload_digest="digest",
        config_digest="config",
        command_json=command.model_dump_json(),
        snapshot_json=json.dumps(snapshot),
        status=view.status.value,
        created_at=created_at,
    )


async def test_history_is_bounded_task_scoped_and_does_not_read_result_blobs(
    session: AsyncSession,
) -> None:
    task_id: UUID = await create_task(session)
    other_task: UUID = await create_task(session)
    created_at: datetime = datetime.now(UTC)
    rows: list[ExtractionRow] = [
        extraction_row(task_id, created_at + timedelta(seconds=index)) for index in range(3)
    ]
    session.add_all([*rows, extraction_row(other_task, created_at + timedelta(days=1))])
    await session.flush()
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(session, task_id=task_id)
    history: list[StoredExtractionSummary] = await store.list_history(limit=1, offset=1)
    assert [item.id for item in history] == [rows[1].id, rows[0].id]
    assert history[0].progress.completed_parts == 1
    assert history[0].analysis_scope == "Current scope"
    assert len(await store.list_history(limit=1, offset=2)) == 1
    assert (await store.get_status(rows[2].id)).id == rows[2].id
    with pytest.raises(Missing):
        await SqlAlchemyExtractionStore(session, task_id=other_task).get_status(rows[2].id)
    with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
        await store.get(rows[2].id)


async def test_operation_lookup_uses_exact_command_and_task(session: AsyncSession) -> None:
    task_id: UUID = await create_task(session)
    other_task: UUID = await create_task(session)
    row: ExtractionRow = extraction_row(task_id, datetime.now(UTC))
    snapshot: dict[str, object] = json.loads(row.snapshot_json)
    snapshot["requirements"] = []
    row.snapshot_json = json.dumps(snapshot)
    session.add(row)
    await session.flush()
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(session, task_id=task_id)
    assert (await store.get_operation(row.operation_id)).id == row.id
    with pytest.raises(Missing):
        await store.get_operation(uuid4())
    with pytest.raises(Missing):
        await SqlAlchemyExtractionStore(session, task_id=other_task).get_operation(row.operation_id)


async def test_history_and_status_api_return_compact_current_configuration(
    session: AsyncSession, browser_client: tuple[httpx.AsyncClient, UUID]
) -> None:
    client: httpx.AsyncClient = browser_client[0]
    created_at: datetime = datetime.now(UTC)
    rows: list[ExtractionRow] = [
        extraction_row(browser_client[1], created_at + timedelta(seconds=index))
        for index in range(2)
    ]
    session.add_all(rows)
    await session.flush()
    response: httpx.Response = await client.get("/api/extractions/history?limit=1")
    assert response.status_code == 200
    payload: dict[str, object] = response.json()
    assert payload["has_more"] is True
    status_response: httpx.Response = await client.get(f"/api/extractions/{rows[1].id}/status")
    summary: dict[str, object] = status_response.json()
    assert payload["items"] == [summary]
    assert summary["id"] == str(rows[1].id)
    assert summary["configuration_current"] is True
    assert set(summary) == {
        "id",
        "status",
        "progress",
        "error_code",
        "created_at",
        "model",
        "version_ids",
        "analysis_scope",
        "configuration_current",
    }
    response = await client.get("/api/extractions/history?limit=1&offset=1")
    payload = response.json()
    assert payload["has_more"] is False
    snapshot: dict[str, object] = json.loads(rows[1].snapshot_json)
    snapshot["prompt_version"] = "older-prompt"
    rows[1].snapshot_json = json.dumps(snapshot)
    await session.flush()
    status_response = await client.get(f"/api/extractions/{rows[1].id}/status")
    summary = status_response.json()
    assert summary["configuration_current"] is False


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
async def test_history_api_rejects_unbounded_pagination(
    browser_client: tuple[httpx.AsyncClient, UUID], query: str
) -> None:
    assert (await browser_client[0].get(f"/api/extractions/history?{query}")).status_code == 422


async def test_operation_api_recovers_specific_execution(
    session: AsyncSession, browser_client: tuple[httpx.AsyncClient, UUID]
) -> None:
    row: ExtractionRow = extraction_row(browser_client[1], datetime.now(UTC))
    snapshot: dict[str, object] = json.loads(row.snapshot_json)
    snapshot["requirements"] = []
    row.snapshot_json = json.dumps(snapshot)
    session.add(row)
    await session.flush()
    response: httpx.Response = await browser_client[0].get(
        f"/api/extraction-operations/{row.operation_id}"
    )
    assert response.status_code == 200
    assert ExtractionView.model_validate_json(response.content).id == row.id
    assert (await browser_client[0].get(f"/api/extraction-operations/{uuid4()}")).status_code == 404


async def test_matching_api_finds_prior_runs_beyond_history_and_matches_exact_version_set(
    session: AsyncSession, browser_client: tuple[httpx.AsyncClient, UUID]
) -> None:
    versions: list[UUID] = [uuid4(), uuid4()]
    task_id: UUID = browser_client[1]
    created_at: datetime = datetime.now(UTC)
    active: ExtractionRow = extraction_row(task_id, created_at)
    current: ExtractionRow = extraction_row(task_id, created_at + timedelta(seconds=1))
    stale: ExtractionRow = extraction_row(task_id, created_at + timedelta(seconds=2))
    current.status = stale.status = RunStatus.COMPLETED.value
    snapshot: dict[str, object] = json.loads(stale.snapshot_json)
    snapshot["prompt_version"] = "older-prompt"
    stale.snapshot_json = json.dumps(snapshot)
    row: ExtractionRow
    for row in (active, current, stale):
        row.command_json = ExtractionStart(
            operation_id=row.operation_id, version_ids=versions, analysis_scope=""
        ).model_dump_json()
    newer: list[ExtractionRow] = [
        extraction_row(task_id, created_at + timedelta(days=index + 1)) for index in range(51)
    ]
    for row in newer:
        row.status = RunStatus.FAILED.value
        row.command_json = ExtractionStart(
            operation_id=row.operation_id, version_ids=versions, analysis_scope=""
        ).model_dump_json()
    session.add_all([active, current, stale, *newer])
    await session.flush()
    response: httpx.Response = await browser_client[0].get(
        "/api/extractions/matching",
        params={
            "version_ids": [str(version) for version in reversed(versions)],
            "analysis_scope": "",
        },
    )
    assert response.status_code == 200
    payload: dict[str, dict[str, object] | None] = response.json()
    assert payload["active"] is not None
    assert payload["active"]["id"] == str(active.id)
    assert payload["current_completed"] is not None
    assert payload["current_completed"]["id"] == str(current.id)
    assert payload["latest_completed"] is not None
    assert payload["latest_completed"]["id"] == str(stale.id)
    response = await browser_client[0].get(
        "/api/extractions/matching", params={"version_ids": str(versions[0]), "analysis_scope": ""}
    )
    assert response.json() == {"active": None, "current_completed": None, "latest_completed": None}
    response = await browser_client[0].get(
        "/api/extractions/matching",
        params={
            "version_ids": [str(version) for version in versions],
            "analysis_scope": "Other scope",
        },
    )
    assert response.json() == {"active": None, "current_completed": None, "latest_completed": None}


async def test_matching_api_requires_explicit_scope(
    browser_client: tuple[httpx.AsyncClient, UUID],
) -> None:
    response: httpx.Response = await browser_client[0].get(
        "/api/extractions/matching", params={"version_ids": str(uuid4())}
    )
    assert response.status_code == 422


async def test_documents_select_latest_completed_version_in_one_query(
    session: AsyncSession,
) -> None:
    task_id: UUID = await create_task(session)
    file_id: UUID = uuid4()
    created_at: datetime = datetime.now(UTC)
    session.add(DocumentRow(file_id=file_id, task_id=task_id, name="BRD", created_at=created_at))
    await session.flush()
    version_id: UUID = uuid4()
    session.add(
        DocumentVersionRow(
            file_id=file_id,
            task_id=task_id,
            version_id=version_id,
            sha256="a" * 64,
            mime_type="text/plain",
            size=1,
            original_name="BRD.txt",
            uploaded_at=created_at,
            storage_key=str(version_id),
        )
    )
    older_version_id: UUID = uuid4()
    session.add(
        DocumentVersionRow(
            file_id=file_id,
            task_id=task_id,
            version_id=older_version_id,
            sha256="d" * 64,
            mime_type="text/plain",
            size=1,
            original_name="Old BRD.txt",
            uploaded_at=created_at - timedelta(days=1),
            storage_key=str(older_version_id),
        )
    )
    await session.flush()
    store: SqlAlchemyDocumentStore = SqlAlchemyDocumentStore(session, task_id=task_id)
    await store.prepare(
        UploadDocument(
            operation_id=uuid4(),
            file_id=file_id,
            filename="New revision.txt",
            mime_type="text/plain",
        ),
        1,
        "b" * 64,
        "c" * 64,
    )
    await store.prepare(
        UploadDocument(operation_id=uuid4(), filename="Prepared only.txt", mime_type="text/plain"),
        1,
        "e" * 64,
        "f" * 64,
    )
    queries: list[str] = []

    def capture_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        queries.append(statement)

    connection: AsyncConnection = await session.connection()
    event.listen(connection.sync_connection, "before_cursor_execute", capture_query)
    try:
        documents: list[DocumentView] = await store.list_documents()
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture_query)
    assert len(queries) == 1
    assert len(documents) == 2
    assert documents[0].latest_version is None
    assert documents[1].latest_version is not None
    assert documents[1].latest_version.version_id == version_id

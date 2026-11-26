import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
from dishka import AsyncContainer, make_async_container
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from solution_architect_ai.application.document_dto import DocumentVersionView, UploadDocument
from solution_architect_ai.application.documents import DocumentService
from solution_architect_ai.application.errors import Conflict, Missing
from solution_architect_ai.application.extraction import ExtractionService
from solution_architect_ai.application.extraction_agent import (
    AgentRequest,
    AgentResult,
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.extraction_context import ContextPack
from solution_architect_ai.application.extraction_models import (
    ExtractionStart,
    ExtractionView,
    PartResult,
)
from solution_architect_ai.application.extraction_ports import (
    ExtractionGraph,
    ExtractionStore,
    ExtractionStoreFactory,
)
from solution_architect_ai.application.extraction_steps import ExtractionSteps
from solution_architect_ai.application.extraction_worker import ExtractionWorker
from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.structured_models import BudgetUsage, ExecutionBudget
from solution_architect_ai.config.models import (
    GitSettings,
    LLMSettings,
    RetryConfig,
    StorageSettings,
)
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.documents import DocumentProvider
from solution_architect_ai.di.extraction import ExtractionProvider
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.domain.requirements import EvidenceStatus
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.extraction_graph import LangGraphExtraction
from solution_architect_ai.persistence.extraction_factory import SqlAlchemyExtractionStoreFactory
from solution_architect_ai.persistence.extraction_models import ExtractionPartRow, RequirementRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]
ORIGINAL: Final[str] = "\n".join(
    ("# Отчётность", "", "## Требования", "Система должна сохранять отчёты.", "")
)


@dataclass
class ExtractionResources:
    container: AsyncContainer
    settings: Settings
    documents: DocumentService
    stores: ExtractionStoreFactory
    service: ExtractionService
    runs: list[UUID]

    async def start(self, versions: list[UUID], scope: str = "") -> ExtractionView:
        view: ExtractionView = await self.service.start(
            ExtractionStart(operation_id=uuid4(), version_ids=versions, analysis_scope=scope)
        )
        self.runs.append(view.id)
        return view

    async def view(self, run_id: UUID) -> ExtractionView:
        return await self.service.get(run_id)

    async def running(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            await store.set_status(run_id, RunStatus.RUNNING)


@pytest.fixture(name="resources")
async def extraction_resources(tmp_path: Path) -> AsyncIterator[ExtractionResources]:
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
        await container.get(ExtractionStoreFactory),
        await container.get(ExtractionService),
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


async def upload(
    resources: ExtractionResources, text: str = ORIGINAL, file_id: UUID | None = None
) -> DocumentVersionView:
    async def chunks() -> AsyncIterator[bytes]:
        yield text.encode()

    return await resources.documents.upload(
        UploadDocument(
            operation_id=uuid4(), filename="BRD.md", mime_type="text/markdown", file_id=file_id
        ),
        chunks(),
    )


async def part_records(resources: ExtractionResources, run_id: UUID) -> list[PartResult]:
    store: ExtractionStore
    async with resources.stores.open() as store:
        return await store.parts(run_id)


async def test_extraction_replay_new_revision_and_history_are_independent_of_chats(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[version.version_id]
    )
    first: ExtractionView
    replay: ExtractionView
    first, replay = await asyncio.gather(
        resources.service.start(command), resources.service.start(command)
    )
    resources.runs.append(first.id)
    assert first.id == replay.id
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(first.id)
    completed: ExtractionView = await resources.view(first.id)
    assert completed.status == RunStatus.COMPLETED
    assert completed.requirements
    assert completed.coverage.complete
    assert completed.requests == completed.progress.total_parts
    assert all(
        source.status == EvidenceStatus.VERIFIED
        for item in completed.requirements
        for source in item.sources
    )
    assert all(
        source.version_id == version.version_id
        for item in completed.requirements
        for source in item.sources
    )
    ids: list[UUID] = [item.id for item in completed.requirements]
    assert (await resources.service.start(command)).id == first.id
    changed: ExtractionStart = command.model_copy(update={"analysis_scope": "другая область"})
    with pytest.raises(Conflict):
        await resources.service.start(changed)
    revision: DocumentVersionView = await upload(
        resources,
        "\n".join(("# Отчётность", "Система должна архивировать отчёты.", "")),
        version.file_id,
    )
    second: ExtractionView = await resources.start([revision.version_id])
    await worker.execute(second.id)
    assert second.id != first.id
    assert (await resources.view(second.id)).status == RunStatus.COMPLETED
    assert [item.id for item in (await resources.view(first.id)).requirements] == ids
    assert await resources.documents.read(version.version_id) == ORIGINAL.encode()
    assert version.sha256 != revision.sha256


async def test_graph_replays_saved_part_without_second_generation_or_duplicate_requirements(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)
    await steps.prepare(run.id)
    assert await steps.extract(run.id, 0) == 1
    parts: list[PartResult] = await part_records(resources, run.id)
    saved_ids: list[UUID] = [item.id for item in parts[0].requirements]
    requests_before: int = (await resources.view(run.id)).requests
    assert await steps.extract(run.id, 0) == 1
    assert (await resources.view(run.id)).requests == requests_before
    graph: ExtractionGraph = await resources.container.get(ExtractionGraph)
    await graph.run(run.id)
    await graph.run(run.id)
    completed: ExtractionView = await resources.view(run.id)
    assert completed.status == RunStatus.COMPLETED
    assert completed.requests == completed.progress.total_parts
    assert set(saved_ids).issubset({item.id for item in completed.requirements})
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    async with engine.connect() as connection:
        count: int | None = await connection.scalar(
            select(func.count()).select_from(RequirementRow).where(RequirementRow.run_id == run.id)
        )
    assert count == len(completed.requirements)


async def test_postgres_checkpoint_survives_resource_restart_after_saved_extraction(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)

    async def crash_before_merge(_run_id: UUID) -> None:
        raise RuntimeError("simulated process interruption after persisted part")

    monkeypatch.setattr(steps, "merge", crash_before_merge)
    graph: ExtractionGraph = await resources.container.get(ExtractionGraph)
    assert isinstance(graph, LangGraphExtraction)
    with pytest.raises(RuntimeError):
        await graph.run(run.id)
    saved: list[PartResult] = await part_records(resources, run.id)
    assert saved
    config: RunnableConfig = {"configurable": {"thread_id": str(run.id)}}
    checkpoint: object = await graph.graph.aget_state(config)
    assert isinstance(checkpoint, StateSnapshot)
    assert checkpoint.next == ("merge",)
    assert set(checkpoint.values) == {"run_id", "index"}
    requests_before: int = (await resources.view(run.id)).requests
    await resources.container.close()
    restored: AsyncContainer = make_async_container(
        AppProvider(),
        DocumentProvider(),
        ExtractionProvider(),
        context={Settings: resources.settings},
    )
    resources.container = restored
    resources.stores = await restored.get(ExtractionStoreFactory)
    resources.service = await restored.get(ExtractionService)
    worker: ExtractionWorker = await restored.get(ExtractionWorker)
    await worker.execute(run.id)
    completed: ExtractionView = await resources.view(run.id)
    assert completed.status == RunStatus.COMPLETED
    assert completed.requests == requests_before
    assert {item.id for item in completed.requirements} == {
        item.id for part in saved for item in part.requirements
    }


async def test_shared_budget_across_parts_preserves_completed_candidates_on_failure(
    resources: ExtractionResources,
) -> None:
    large: str = "\n\n".join(
        "\n".join((f"## Раздел {index}", f"Система должна сохранять отчёт {index}. "))
        + "Проверяемое условие обработки. " * 70
        for index in range(12)
    )
    version: DocumentVersionView = await upload(resources, large)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    original: ExtractionSteps = await resources.container.get(ExtractionSteps)
    limited: ExtractionSteps = ExtractionSteps(
        original.stores,
        original.documents,
        original.builder,
        original.agent,
        replace(original.policy, requests=1),
    )
    pack: ContextPack = await limited.context(run.id)
    assert len(pack.parts) > 1
    await original.prepare(run.id)
    await limited.extract(run.id, 0)
    first: list[PartResult] = await part_records(resources, run.id)
    assert first[0].requirements
    with pytest.raises(StructuredGenerationFailure) as raised:
        await limited.extract(run.id, 1)
    assert raised.value.reason == StructuredErrorCode.BUDGET_EXHAUSTED
    store: ExtractionStore
    async with resources.stores.open() as store:
        await store.set_status(run.id, RunStatus.FAILED, raised.value.reason.value)
    failed: ExtractionView = await resources.view(run.id)
    assert failed.requests == 1
    assert failed.progress.completed_parts == 1
    assert failed.requirements == first[0].requirements
    assert failed.coverage.processed_fragments > 0
    assert failed.coverage.processed_fragments < failed.coverage.total_fragments
    assert failed.coverage.complete is False


async def test_concurrent_request_reservations_reject_stale_budget(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)

    async def reserve_once() -> bool:
        store: ExtractionStore
        try:
            async with resources.stores.open() as store:
                await store.reserve(run.id, BudgetUsage(1, 0, 0), expected_requests=0)
            return True
        except Conflict:
            return False

    outcomes: list[bool] = list(await asyncio.gather(reserve_once(), reserve_once()))
    assert sorted(outcomes) == [False, True]
    assert (await resources.view(run.id)).requests == 1


async def test_cancel_before_claim_prevents_graph_and_llm_requests(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.service.cancel(run.id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    cancelled: ExtractionView = await resources.view(run.id)
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.requests == 0
    assert cancelled.requirements == []
    assert (await resources.service.cancel(run.id)).status == RunStatus.CANCELLED


async def test_cancellation_after_response_prevents_late_candidate_persistence(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    agent: RequirementsExtractionAgent = await resources.container.get(RequirementsExtractionAgent)
    original: Callable[[AgentRequest, ExecutionBudget], Awaitable[AgentResult]] = agent.extract

    async def cancelled_response(request: AgentRequest, budget: ExecutionBudget) -> AgentResult:
        result: AgentResult = await original(request, budget)
        await resources.service.cancel(run.id)
        return result

    monkeypatch.setattr(agent, "extract", cancelled_response)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    cancelled: ExtractionView = await resources.view(run.id)
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.requests == 1
    assert cancelled.requirements == []
    assert await part_records(resources, run.id) == []


async def test_changed_model_profile_fails_with_saved_provenance(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)
    monkeypatch.setattr(steps, "policy", replace(steps.policy, config_digest="different-profile"))
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    failed: ExtractionView = await resources.view(run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "model_profile_changed"
    assert failed.requests == 0
    assert failed.model_profile == run.model_profile
    assert "api_key" not in failed.model_profile.model_dump_json()


async def test_corrupted_original_invalidates_saved_parse_before_generation(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    await resources.documents.parsed(version.version_id)
    run: ExtractionView = await resources.start([version.version_id])
    path: Path = resources.settings.storage.root / version.storage_key
    await asyncio.to_thread(path.write_bytes, b"corrupted original")
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    failed: ExtractionView = await resources.view(run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "document_file_corrupt"
    assert failed.requests == 0


async def test_other_task_cannot_read_extraction_or_candidates(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    original: SqlAlchemyExtractionStoreFactory
    assert isinstance(resources.stores, SqlAlchemyExtractionStoreFactory)
    original = resources.stores
    foreign: SqlAlchemyExtractionStoreFactory = SqlAlchemyExtractionStoreFactory(
        original.sessions, task_id=uuid4()
    )
    store: ExtractionStore
    async with foreign.open() as store:
        with pytest.raises(Missing):
            await store.get(run.id)
        assert all(item.id != run.id for item in await store.list_runs())


async def test_checkpoint_resume_at_save_revalidates_the_original(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)
    original: Callable[[UUID], Awaitable[None]] = steps.save

    async def interrupted(_run_id: UUID) -> None:
        raise RuntimeError("process stopped after source verification checkpoint")

    monkeypatch.setattr(steps, "save", interrupted)
    graph: ExtractionGraph = await resources.container.get(ExtractionGraph)
    with pytest.raises(RuntimeError, match="process stopped"):
        await graph.run(run.id)
    requests_before: int = (await resources.view(run.id)).requests
    await asyncio.to_thread((resources.settings.storage.root / version.storage_key).unlink)
    monkeypatch.setattr(steps, "save", original)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    failed: ExtractionView = await resources.view(run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "document_file_missing"
    assert failed.requests == requests_before
    assert all(
        source.status == EvidenceStatus.UNVERIFIED
        for item in failed.requirements
        for source in item.sources
    )


async def test_resume_rejects_changed_context_manifest_without_a_new_request(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)
    await steps.prepare(run.id)
    await steps.extract(run.id, 0)
    previous: int = (await resources.view(run.id)).requests
    monkeypatch.setattr(steps.builder, "schema", steps.builder.schema + " ")
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    failed: ExtractionView = await resources.view(run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "context_changed"
    assert failed.requests == previous


async def test_corrupt_saved_part_is_quarantined_without_cancelling_siblings(
    resources: ExtractionResources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.start([version.version_id])
    await resources.running(run.id)
    steps: ExtractionSteps = await resources.container.get(ExtractionSteps)
    await steps.prepare(run.id)
    await steps.extract(run.id, 0)
    engine: AsyncEngine = await resources.container.get(AsyncEngine)
    connection: AsyncConnection
    async with engine.begin() as connection:
        await connection.execute(
            update(ExtractionPartRow)
            .where(ExtractionPartRow.run_id == run.id)
            .values(result_json="{")
        )
    sibling_finished: asyncio.Event = asyncio.Event()

    async def sibling() -> None:
        await asyncio.sleep(0.1)
        sibling_finished.set()

    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        group.create_task(worker.execute(run.id))
        group.create_task(sibling())
    failed: ExtractionView = await resources.view(run.id)
    assert sibling_finished.is_set()
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == "stored_result_corrupt"
    assert failed.coverage.complete is False
    assert "stored_result_corrupt" in failed.coverage.warnings

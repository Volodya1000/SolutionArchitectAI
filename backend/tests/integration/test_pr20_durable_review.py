from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Final
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.test_helpers.bounded_review_model import CrossSectionModel
from backend.test_helpers.clarification_graph import start_fresh
from backend.test_helpers.clarification_history import seed_analysis
from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.sql_store_setup import SqlStoreSetup, clarification_store_setup
from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.errors.chat_errors import Missing, StorageUnavailable
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationView,
)
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
    QuestionWindowResult,
)
from solution_architect_ai.application.models.extraction_agent_models import (
    AgentRequest,
    AgentResult,
)
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedRequirement,
    ExtractionView,
    RequirementsExtraction,
    RequirementView,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.clarification_workflow import ClarificationWorkflow
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationStepRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class ReviewReplayCase:
    workflow: ClarificationWorkflow
    stores: SqlStoreSetup[SqlAlchemyClarificationStore]
    run_id: UUID
    model: CrossSectionModel
    context: ClarificationContext


@pytest.fixture(name="review_replay")
async def review_replay_fixture(
    resources: ExtractionResources,
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    monkeypatch: pytest.MonkeyPatch,
) -> ReviewReplayCase:
    fragments: tuple[DocumentFragment, ...] = tuple(
        DocumentFragment(uuid4(), text, SourceLocator(LocatorKind.LINES, index + 1, index + 1))
        for index, text in enumerate(
            [
                "Доступ требует уточнения. " + "Условия источника. " * 100,
                *["Прочие положения. " * 100 for _ in range(6)],
                "При отказе отклонить запрос. " + "Последние условия. " * 100,
            ]
        )
    )
    source: ParsedDocument = ParsedDocument(
        uuid4(),
        uuid4(),
        "a" * 64,
        "test",
        "\n".join(item.text for item in fragments),
        fragments,
    )
    requirement: RequirementView = referenced_requirement(source, fragments[0])
    requirement.original_text = requirement.normalized_text = "Доступ требует уточнения."
    requirement.sources[0].quote = "Доступ требует уточнения."
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        row: ExtractionRow = await store.extraction(run_id)
        snapshot: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        snapshot.status = RunStatus.RUNNING
        row.status, row.snapshot_json = snapshot.status.value, snapshot.model_dump_json()
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    workflow: ClarificationWorkflow = await resources.container.get(ClarificationWorkflow)
    model: CrossSectionModel = CrossSectionModel()
    workflow.clarification_agent.structured_output_generator = StructuredOutputGenerator(
        model,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )

    async def build_context(_run_id: UUID, _view: ClarificationView) -> ClarificationContext:
        return context

    monkeypatch.setattr(workflow, "build_context", build_context)
    assert (
        len(
            await ClarificationContextPlanner(
                workflow.clarification_agent.structured_output_generator, 2
            ).plan(context)
        )
        > 1
    )
    return ReviewReplayCase(workflow, decision_stores, run_id, model, context)


@pytest.mark.parametrize("assess_conflict", [False, True])
async def test_validated_questions_and_source_verdicts_survive_crash_before_question_save(
    review_replay: ReviewReplayCase, monkeypatch: pytest.MonkeyPatch, assess_conflict: bool
) -> None:
    if assess_conflict:
        review_replay.context.requirements[0].category = RequirementCategory.CONTRADICTION
    original_save: Callable[
        [
            SqlAlchemyClarificationStore,
            UUID,
            list[ClarificationQuestion],
            ClarificationMetadata | None,
        ],
        Awaitable[None],
    ] = SqlAlchemyClarificationStore.save_questions

    async def crash_before_save(
        _self: SqlAlchemyClarificationStore,
        _run_id: UUID,
        _questions: list[ClarificationQuestion],
        _metadata: ClarificationMetadata | None = None,
    ) -> None:
        raise StorageUnavailable("crash_before_final_question_commit")

    monkeypatch.setattr(SqlAlchemyClarificationStore, "save_questions", crash_before_save)
    with pytest.raises(StorageUnavailable, match="crash_before_final_question_commit"):
        await review_replay.workflow.prepare_questions(review_replay.run_id)
    requests_before_restart: int = len(review_replay.model.requests)
    assert requests_before_restart > 2
    assert any(
        '"role":"clarification_review"' in item.messages[-1].content
        for item in review_replay.model.requests
    )
    monkeypatch.setattr(SqlAlchemyClarificationStore, "save_questions", original_save)
    await review_replay.workflow.prepare_questions(review_replay.run_id)
    assert len(review_replay.model.requests) == requests_before_restart
    store: SqlAlchemyClarificationStore
    async with review_replay.stores.open() as store:
        view: ClarificationView = await store.get(review_replay.run_id)
        assert view.initialized
        assert view.questions == []
        assert view.metadata is not None
        assert view.metadata.coverage is not None
        assert view.metadata.coverage.complete
        assert view.metadata.coverage.reviewed_fragments == len(
            review_replay.context.part.fragments
        )
        assert view.metadata.coverage.model_requests == requests_before_restart
        if assess_conflict:
            assert view.conflict_assessments[0].status == "refuted"


async def test_completed_window_survives_crash_before_progress_metadata_commit(
    review_replay: ReviewReplayCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_metadata: Callable[
        [SqlAlchemyClarificationStore, UUID, ClarificationMetadata], Awaitable[None]
    ] = SqlAlchemyClarificationStore.set_review_metadata

    async def crash_after_window(
        store: SqlAlchemyClarificationStore, run_id: UUID, metadata: ClarificationMetadata
    ) -> None:
        if metadata.coverage is not None and metadata.coverage.reviewed_fragments:
            raise StorageUnavailable("crash_after_validated_window_commit")
        await original_metadata(store, run_id, metadata)

    monkeypatch.setattr(SqlAlchemyClarificationStore, "set_review_metadata", crash_after_window)
    with pytest.raises(StorageUnavailable, match="crash_after_validated_window_commit"):
        await review_replay.workflow.prepare_questions(review_replay.run_id)
    assert len(review_replay.model.requests) == 1
    first_request: str = review_replay.model.requests[0].messages[-1].content
    monkeypatch.setattr(SqlAlchemyClarificationStore, "set_review_metadata", original_metadata)
    await review_replay.workflow.prepare_questions(review_replay.run_id)
    assert (
        sum(item.messages[-1].content == first_request for item in review_replay.model.requests)
        == 1
    )
    store: SqlAlchemyClarificationStore
    async with review_replay.stores.open() as store:
        view: ClarificationView = await store.get(review_replay.run_id)
        assert view.initialized
        assert view.metadata is not None
        assert view.metadata.coverage is not None
        assert view.metadata.coverage.complete
        assert view.metadata.coverage.model_requests == len(review_replay.model.requests)


async def test_graph_restarts_clarify_node_without_repeating_completed_window(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction_agent: RequirementsExtractionAgent = await resources.container.get(
        RequirementsExtractionAgent
    )

    async def extract(request: AgentRequest, _budget: ExecutionBudget) -> AgentResult:
        evidence: Evidence = Evidence(
            fragment_id=str(request.part.fragments[0].fragment_id),
            quote=request.part.fragments[0].text[:30],
        )
        return AgentResult(
            request.run_id,
            request.attempt_id,
            RequirementsExtraction(
                requirements=[
                    ExtractedRequirement(
                        category=RequirementCategory.FUNCTIONAL,
                        original_text=evidence.quote,
                        normalized_text=evidence.quote,
                        evidence=[evidence],
                    )
                ],
                gaps=[],
                contradictions=[],
            ),
        )

    monkeypatch.setattr(extraction_agent, "extract", extract)
    workflow: ClarificationWorkflow = await resources.container.get(ClarificationWorkflow)
    original_build: Callable[[UUID, ClarificationView], Awaitable[ClarificationContext]] = (
        workflow.build_context
    )

    async def build(run_id: UUID, view: ClarificationView) -> ClarificationContext:
        context: ClarificationContext = await original_build(run_id, view)
        return replace(
            context, profile=replace(context.profile, context_window=4800, output_limit=512)
        )

    monkeypatch.setattr(workflow, "build_context", build)
    model: CrossSectionModel = CrossSectionModel()
    workflow.clarification_agent.structured_output_generator = StructuredOutputGenerator(
        model,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    original_metadata: Callable[
        [SqlAlchemyClarificationStore, UUID, ClarificationMetadata], Awaitable[None]
    ] = SqlAlchemyClarificationStore.set_review_metadata

    async def crash_after_window(
        store: SqlAlchemyClarificationStore, run_id: UUID, metadata: ClarificationMetadata
    ) -> None:
        if metadata.coverage is not None and metadata.coverage.reviewed_fragments:
            raise StorageUnavailable("process_stopped_after_window")
        await original_metadata(store, run_id, metadata)

    monkeypatch.setattr(SqlAlchemyClarificationStore, "set_review_metadata", crash_after_window)
    version_id: UUID = (
        await upload(
            resources,
            "\n\n".join(
                [
                    "Доступ требует уточнения. " + "Условия источника. " * 100,
                    *["Прочие положения. " * 100 for _ in range(6)],
                    "При отказе отклонить запрос. " + "Последние условия. " * 100,
                ]
            ),
        )
    ).version_id
    run_id: UUID = (await start_fresh(resources, version_id)).id
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run_id)
    assert (await resources.view(run_id)).status == RunStatus.RUNNING
    completed_requests: list[str] = [item.messages[-1].content for item in model.requests]
    assert completed_requests
    monkeypatch.setattr(SqlAlchemyClarificationStore, "set_review_metadata", original_metadata)
    restarted: ExtractionWorker = ExtractionWorker(
        worker.extraction_store_context,
        worker.extraction_graph,
        worker.capacity,
        worker.deadline,
        worker.clarification_store_context,
    )
    await restarted.execute(run_id)
    assert (await resources.view(run_id)).status == RunStatus.COMPLETED
    assert all(
        sum(item.messages[-1].content == previous for item in model.requests) == 1
        for previous in completed_requests
    )


async def test_failed_model_output_is_not_cached_and_replay_keeps_failed_request_count(
    review_replay: ReviewReplayCase,
) -> None:
    review_replay.workflow.clarification_agent.structured_output_generator.structured_model = (
        ClarificationModel("not JSON")
    )
    with pytest.raises(StructuredGenerationFailure):
        await review_replay.workflow.prepare_questions(review_replay.run_id)
    store: SqlAlchemyClarificationStore
    async with review_replay.stores.open() as store:
        assert (
            await store.session.scalar(
                select(func.count())
                .select_from(ClarificationStepRow)
                .where(ClarificationStepRow.run_id == review_replay.run_id)
            )
            == 0
        )
        failed: ClarificationView = await store.get(review_replay.run_id)
        assert failed.metadata is not None
        assert failed.metadata.coverage is not None
        failed_requests: int = failed.metadata.coverage.model_requests
    review_replay.workflow.clarification_agent.structured_output_generator.structured_model = (
        review_replay.model
    )
    await review_replay.workflow.prepare_questions(review_replay.run_id)
    async with review_replay.stores.open() as store:
        view: ClarificationView = await store.get(review_replay.run_id)
        assert view.metadata is not None
        assert view.metadata.coverage is not None
        assert view.metadata.coverage.model_requests == failed_requests + len(
            review_replay.model.requests
        )


async def test_cached_foreign_requirement_is_rejected_and_foreign_actor_cannot_read_step(
    review_replay: ReviewReplayCase,
) -> None:
    await review_replay.workflow.prepare_questions(review_replay.run_id)
    before_requests: int = len(review_replay.model.requests)
    store: SqlAlchemyClarificationStore
    async with review_replay.stores.open() as store:
        rows: list[ClarificationStepRow] = list(
            await store.session.scalars(
                select(ClarificationStepRow).where(
                    ClarificationStepRow.run_id == review_replay.run_id
                )
            )
        )
        row: ClarificationStepRow
        for row in rows:
            result: ClarificationStepResult | None = await store.get_review_step(
                review_replay.run_id, row.step_key
            )
            if isinstance(result, QuestionWindowResult) and result.questions:
                result.questions[0].requirement_ids = [uuid4()]
                row.result_json = result.model_dump_json()
                break
        else:
            pytest.fail("Expected validated cached question result")
        (await store.run(review_replay.run_id)).initialized = False
    with pytest.raises(StoredExtractionCorrupt):
        await review_replay.workflow.prepare_questions(review_replay.run_id)
    assert len(review_replay.model.requests) == before_requests
    foreign: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        review_replay.stores.sessions, ActorContext.local(uuid4())
    )
    with pytest.raises(Missing, match="extraction"):
        async with foreign.open() as store:
            await store.get_review_step(review_replay.run_id, rows[0].step_key)

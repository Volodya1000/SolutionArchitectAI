from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.bounded_review_model import CrossSectionModel
from backend.test_helpers.clarification_graph import answer, install_questions, start_fresh
from backend.test_helpers.clarification_history import (
    establish_conflict,
    prepare_questions,
    seed_analysis,
)
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.conflict_review_model import (
    EstablishedConflictModel,
    RefutedConflictNoQuestionsModel,
)
from backend.test_helpers.document_builders import document
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.requirements_extraction_agent import (
    RequirementsExtractionAgent,
)
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.extraction_agent_models import (
    AgentRequest,
    AgentResult,
)
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractedContradiction,
    ExtractedRequirement,
    RequirementsExtraction,
    RequirementView,
)
from solution_architect_ai.application.models.structured_models import ExecutionBudget
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("known_conflict", [False, True])
async def test_recorded_assumption_does_not_override_established_conflict(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore], known_conflict: bool
) -> None:
    source: ParsedDocument = document(
        uuid4(), "Правило: хранить 30 дней. Требование: удалить через 7 дней."
    )
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.category = (
        RequirementCategory.CONTRADICTION if known_conflict else RequirementCategory.FUNCTIONAL
    )
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    if known_conflict:
        await establish_conflict(decision_stores, run_id, requirement)
    await prepare_questions(decision_stores, run_id, source, requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        before: ClarificationView = await store.get(run_id)
        await store.answer(
            run_id, before.questions[0].id, answer(before.questions[0], assumption=True)
        )
    async with decision_stores.open() as store:
        if known_conflict:
            with pytest.raises(Conflict, match="blocking_questions_open"):
                await store.complete_cycle(run_id, 0)
        else:
            await store.complete_cycle(run_id, 0)
        after: ClarificationView = await store.get(run_id)
        assert len(after.decisions) == len(after.risks) == 1
        assert len(after.completed_cycles) == (0 if known_conflict else 1)
        assert (await store.extraction(run_id)).status == (
            "waiting_input" if known_conflict else "completed"
        )
        if known_conflict:
            assert after.questions[0].mandatory_conflict == requirement.normalized_text


@pytest.mark.parametrize(("known_conflict", "question_count"), [(False, 1), (True, 1), (True, 0)])
async def test_graph_keeps_known_conflict_waiting_after_recording_assumption(
    resources: ExtractionResources,
    monkeypatch: pytest.MonkeyPatch,
    known_conflict: bool,
    question_count: int,
) -> None:
    await install_questions(resources, monkeypatch, count=question_count)
    clarification_agent: ClarificationAgent = await resources.container.get(ClarificationAgent)
    clarification_agent.structured_output_generator.structured_model = EstablishedConflictModel()
    extraction_agent: RequirementsExtractionAgent = await resources.container.get(
        RequirementsExtractionAgent
    )

    async def scripted(request: AgentRequest, _budget: ExecutionBudget) -> AgentResult:
        evidence: list[Evidence] = [
            Evidence(fragment_id=str(item.fragment_id), quote=item.text)
            for item in request.part.fragments
        ]
        payload: RequirementsExtraction = RequirementsExtraction(
            requirements=[]
            if known_conflict
            else [
                ExtractedRequirement(
                    category=RequirementCategory.FUNCTIONAL,
                    original_text=evidence[-1].quote,
                    normalized_text=evidence[-1].quote,
                    evidence=[evidence[-1]],
                )
            ],
            gaps=[],
            contradictions=[
                ExtractedContradiction(
                    description="Обязательные сроки противоречат друг другу", evidence=evidence[-2:]
                )
            ]
            if known_conflict
            else [],
        )
        return AgentResult(request.run_id, request.attempt_id, payload)

    monkeypatch.setattr(extraction_agent, "extract", scripted)
    version_id: UUID = (
        await upload(
            resources, "\n\n".join(("# Правила", "Хранить 30 дней.", "Удалить через 7 дней."))
        )
    ).version_id
    run_id: UUID = (await start_fresh(resources, version_id)).id
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(run_id)
    view: ClarificationView = await service.get(run_id)
    await service.answer(run_id, view.questions[0].id, answer(view.questions[0], assumption=True))
    await worker.execute(run_id)
    after: ClarificationView = await service.get(run_id)
    assert (await resources.view(run_id)).status == (
        RunStatus.WAITING_INPUT if known_conflict else RunStatus.COMPLETED
    )
    assert len(after.decisions) == len(after.risks) == 1
    assert len(after.completed_cycles) == (0 if known_conflict else 1)


@pytest.mark.parametrize(
    ("false_contradiction", "empty_questions"), [(False, False), (True, False), (True, True)]
)
async def test_worker_false_question_refuted_by_selected_source_can_complete(
    resources: ExtractionResources,
    monkeypatch: pytest.MonkeyPatch,
    false_contradiction: bool,
    empty_questions: bool,
) -> None:
    extraction_agent: RequirementsExtractionAgent = await resources.container.get(
        RequirementsExtractionAgent
    )

    async def scripted(request: AgentRequest, _budget: ExecutionBudget) -> AgentResult:
        evidence: Evidence = Evidence(
            fragment_id=str(request.part.fragments[-1].fragment_id),
            quote=request.part.fragments[-1].text,
        )
        return AgentResult(
            request.run_id,
            request.attempt_id,
            RequirementsExtraction(
                requirements=[]
                if false_contradiction
                else [
                    ExtractedRequirement(
                        category=RequirementCategory.FUNCTIONAL,
                        original_text=evidence.quote,
                        normalized_text=evidence.quote,
                        evidence=[evidence],
                    )
                ],
                gaps=[],
                contradictions=[
                    ExtractedContradiction(
                        description="Условия доступа противоречат обработке отказа",
                        evidence=[
                            Evidence(
                                fragment_id=evidence.fragment_id, quote="Доступ требует уточнения."
                            ),
                            Evidence(
                                fragment_id=evidence.fragment_id,
                                quote="При отказе отклонить запрос.",
                            ),
                        ],
                    )
                ]
                if false_contradiction
                else [],
            ),
        )

    monkeypatch.setattr(extraction_agent, "extract", scripted)
    clarification_agent: ClarificationAgent = await resources.container.get(ClarificationAgent)
    model: CrossSectionModel = (
        RefutedConflictNoQuestionsModel() if empty_questions else CrossSectionModel()
    )
    clarification_agent.structured_output_generator = StructuredOutputGenerator(
        model,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    version_id: UUID = (
        await upload(resources, "Доступ требует уточнения. При отказе отклонить запрос.")
    ).version_id
    run_id: UUID = (await start_fresh(resources, version_id)).id
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run_id)
    service: ClarificationService = await resources.container.get(ClarificationService)
    assert (await resources.view(run_id)).status == RunStatus.COMPLETED
    assert (await service.get(run_id)).questions == []
    if false_contradiction:
        result: ClarificationView = await service.get(run_id)
        assert result.conflict_assessments[0].status == "refuted"
        assert result.conflict_assessments[0].sources
    if not empty_questions:
        assert any(
            '"role":"clarification_review"' in request.messages[-1].content
            for request in model.requests
        )

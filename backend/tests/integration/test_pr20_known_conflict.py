from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.tests.integration.test_clarification_commands import (  # pylint: disable=unused-import,useless-import-alias
    decision_stores_fixture as decision_stores_fixture,
)
from backend.tests.integration.test_clarification_graph import (
    answer,
    install_questions,
    start_fresh,
)
from backend.tests.integration.test_clarification_history import (
    document,
    prepare_questions,
    seed_analysis,
)
from backend.tests.integration.test_extraction_lifecycle import ExtractionResources, upload
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from backend.tests.sql_store_setup import SqlStoreSetup
from backend.tests.unit.test_clarification_agent import referenced_requirement
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
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
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


@pytest.mark.parametrize("known_conflict", [False, True])
async def test_graph_keeps_known_conflict_waiting_after_recording_assumption(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch, known_conflict: bool
) -> None:
    await install_questions(resources, monkeypatch, count=1)
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

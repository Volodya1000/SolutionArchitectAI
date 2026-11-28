from typing import Final, Literal
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.clarification_graph import answer
from backend.test_helpers.clarification_history import (
    establish_conflict,
    prepare_questions,
    seed_analysis,
)
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.document_builders import document
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.context.clarification_question_merge import (
    merge_question_windows,
)
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    ResolveAssumption,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
    RequirementView,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory
from solution_architect_ai.persistence.clarifications.clarification_models import (
    DecisionRow,
    RiskRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def test_proven_conflict_persists_when_valid_agent_response_contains_no_questions(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4(), "Mandatory retention 30 days; delete after 7 days.")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.category = RequirementCategory.CONTRADICTION
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    await establish_conflict(decision_stores, run_id, requirement)
    await prepare_questions(decision_stores, run_id, source, requirement, candidate=False)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert len(view.questions) == 1
        assert view.questions[0].mandatory_conflict == requirement.normalized_text
        assert view.questions[0].requirement_ids == [requirement.id]
        assert view.questions[0].sources == requirement.sources
        with pytest.raises(Conflict, match="blocking_questions_open"):
            await store.complete_cycle(run_id, 0)


@pytest.mark.parametrize("confirmation", ["pending", "confirm", "legacy_confirmed"])
async def test_mandatory_assumption_allows_factual_answer_preserving_old_revision_and_risk(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    confirmation: Literal["pending", "confirm", "legacy_confirmed"],
) -> None:
    source: ParsedDocument = document(uuid4(), "Mandatory retention 30 days; delete after 7 days.")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.category = RequirementCategory.CONTRADICTION
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    await establish_conflict(decision_stores, run_id, requirement)
    await prepare_questions(decision_stores, run_id, source, requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        before: ClarificationView = await store.get(run_id)
        assumption: DecisionResult = await store.answer(
            run_id, before.questions[0].id, answer(before.questions[0], assumption=True)
        )
    if confirmation == "legacy_confirmed":
        await restore_legacy_confirmation(decision_stores, run_id, assumption)
    if confirmation == "confirm":
        resolution: ResolveAssumption = ResolveAssumption(
            operation_id=uuid4(),
            expected_revision=1,
            resolution="confirm",
            reason="Assumption checked; mandatory rule still requires factual resolution",
        )
        async with decision_stores.open() as store:
            confirmed: DecisionResult = await store.resolve(assumption.decision_id, resolution)
        async with decision_stores.open() as store:
            assert await store.resolve(assumption.decision_id, resolution) == confirmed
    async with decision_stores.open() as store:
        waiting: ClarificationView = await store.get(run_id)
        assert waiting.questions[0].blocks_completion
        command: AnswerClarification = answer(waiting.questions[0])
        factual: DecisionResult = await store.answer(run_id, waiting.questions[0].id, command)
    async with decision_stores.open() as store:
        assert await store.answer(run_id, waiting.questions[0].id, command) == factual
        await store.complete_cycle(run_id, (await store.get(run_id)).cycle)
        after: ClarificationView = await store.get(run_id)
        assert after.questions[0].status == "answered"
        assert after.questions[0].revision == 2
        assert len(after.decisions) == 2
        assert len(after.risks) == 1
        assert after.decisions[0].question_revision == 1
        assert factual.question_revision == 2
        assert after.resume_pending
        assert len(after.completed_cycles) == 1


async def restore_legacy_confirmation(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore], run_id: UUID, assumption: DecisionResult
) -> None:
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        row: DecisionRow | None = await store.session.get(DecisionRow, assumption.decision_id)
        risk: RiskRow | None = await store.session.get(RiskRow, assumption.risk_id)
        assert row is not None
        assert risk is not None
        assumption.resolution = "confirmed"
        row.snapshot_json = assumption.model_dump_json()
        risk.snapshot_json = (
            (await store.get(run_id))
            .risks[0]
            .model_copy(update={"status": "closed"})
            .model_dump_json()
        )


async def test_merged_answer_applies_to_both_requirements_and_excludes_unrelated_requirement(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4(), "Selected source condition")
    requirements: list[RequirementView] = [
        referenced_requirement(source, source.fragments[0]) for _ in range(3)
    ]
    run_id: UUID = await seed_analysis(decision_stores, source, requirements[0])
    questions: list[ClarificationQuestion] = [
        ClarificationQuestion(
            id=uuid4(),
            gap_key="same-gap",
            text="Clarify",
            basis=f"Basis {index}",
            dependent_decision="Dependent result",
            blocking=index == 0,
            requirement_ids=[requirement.id],
            sources=requirement.sources,
        )
        for index, requirement in enumerate(requirements[:2])
    ]
    merged: ClarificationQuestion = merge_question_windows(questions)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        row: ExtractionRow = await store.extraction(run_id)
        snapshot: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        snapshot.requirements = requirements
        row.snapshot_json = snapshot.model_dump_json()
        await store.save_questions(run_id, [merged])
    async with decision_stores.open() as store:
        decision: DecisionResult = await store.answer(run_id, merged.id, answer(merged))
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert set(decision.requirement_ids) == {item.id for item in requirements[:2]}
        assert all(decision.text in item.normalized_text for item in view.requirements[:2])
        assert decision.text not in view.requirements[2].normalized_text


async def test_unverified_contradiction_hypothesis_remains_diagnostic_without_mandatory_blocker(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4(), "Unverified candidate condition")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.category = RequirementCategory.CONTRADICTION
    requirement.sources[0].status = EvidenceStatus.UNVERIFIED
    requirement.sources[0].reason = "Quote integrity has not been established"
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        await store.save_conflict_assessments(
            run_id,
            [
                ConflictAssessment(
                    requirement_id=requirement.id,
                    status="candidate",
                    reason="Source is unverified",
                    sources=requirement.sources,
                )
            ],
        )
        await store.save_questions(run_id, [])
        await store.complete_cycle(run_id, 0)
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert view.questions == []
        assert view.conflict_assessments[0].status == "candidate"
        assert view.conflict_assessments[0].sources[0].status == EvidenceStatus.UNVERIFIED
        assert len(view.completed_cycles) == 1

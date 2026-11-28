from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.clarification_graph import answer
from backend.test_helpers.clarification_history import (
    answer_command,
    establish_conflict,
    prepare_questions,
    seed_analysis,
)
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.document_builders import document
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.models.clarification_models import (
    ClarificationMetadata,
    ClarificationQuestion,
    ClarificationReviewCoverage,
    ClarificationView,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import ModelProfile, StructuredMode
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.persistence.clarifications.clarification_models import (
    QuestionRevisionRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def test_legacy_fingerprints_cannot_inherit_answer_for_changed_statement_in_same_fragment(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4(), "Хранение 30 дней. Для администратора 7 дней.")
    original: RequirementView = referenced_requirement(source, source.fragments[0])
    original.original_text = original.normalized_text = "Хранение 30 дней."
    run_id: UUID = await seed_analysis(decision_stores, source, original)
    await prepare_questions(decision_stores, run_id, source, original)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        await store.answer(run_id, view.questions[0].id, answer_command(view.questions[0]))
        revision: QuestionRevisionRow = await store.question(run_id, view.questions[0].id)
        old: ClarificationQuestion = ClarificationQuestion.model_validate_json(
            revision.snapshot_json
        )
        revision.snapshot_json = old.model_dump_json(exclude={"requirement_basis_fingerprints"})
    current: RequirementView = referenced_requirement(source, source.fragments[0])
    current.original_text = current.normalized_text = "Для администратора 7 дней."
    next_id: UUID = await seed_analysis(decision_stores, source, current, run_id)
    await prepare_questions(decision_stores, next_id, source, current, changed_basis=False)
    async with decision_stores.open() as store:
        updated: ClarificationView = await store.get(next_id)
        assert updated.questions[0].revision == 2
        assert updated.questions[0].status == "open"
        assert "Повторить запрос" not in updated.requirements[0].normalized_text


async def test_known_conflict_cannot_complete_with_legacy_nonblocking_flag(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(
        uuid4(), "Правило: хранить 30 дней. Требование: удалить через 7 дней."
    )
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.category = RequirementCategory.CONTRADICTION
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    await establish_conflict(decision_stores, run_id, requirement)
    await prepare_questions(decision_stores, run_id, source, requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        before: ClarificationView = await store.get(run_id)
        revision: QuestionRevisionRow = await store.question(run_id, before.questions[0].id)
        question: ClarificationQuestion = ClarificationQuestion.model_validate_json(
            revision.snapshot_json
        )
        question.blocking = False
        revision.snapshot_json = question.model_dump_json()
        await store.answer(run_id, question.id, answer(question, assumption=True))
    async with decision_stores.open() as store:
        with pytest.raises(Conflict, match="blocking_questions_open"):
            await store.complete_cycle(run_id, 0)
        after: ClarificationView = await store.get(run_id)
        assert len(after.decisions) == len(after.risks) == 1
        assert after.completed_cycles == []
        assert (await store.extraction(run_id)).status == "waiting_input"


async def test_partial_review_coverage_is_persisted_and_cannot_complete(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4())
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    run_id: UUID = await seed_analysis(decision_stores, source, requirement)
    metadata: ClarificationMetadata = ClarificationMetadata(
        prompt_version="test",
        context_digest="test",
        model_profile=ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512),
        coverage=ClarificationReviewCoverage(
            total_fragments=1, unreviewed_fragment_ids=[str(source.fragments[0].fragment_id)]
        ),
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        await store.set_review_metadata(run_id, metadata)
    async with decision_stores.open() as store:
        assert (await store.get(run_id)).metadata == metadata
        await store.save_questions(run_id, [], metadata)
    async with decision_stores.open() as store:
        with pytest.raises(Conflict, match="clarification_review_incomplete"):
            await store.complete_cycle(run_id, 0)

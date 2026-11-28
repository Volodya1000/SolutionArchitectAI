from dataclasses import replace
from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.clarification_history import (
    answer_command,
    prepare_questions,
    seed_analysis,
)
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.document_builders import document
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.domain.documents import DocumentFragment, ParsedDocument
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("flag", [False, None])
async def test_changed_requirement_reopens_without_model_permission(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore], flag: bool | None
) -> None:
    first: ParsedDocument = document(uuid4(), "Хранить отчёты 30 дней.")
    original: RequirementView = referenced_requirement(first, first.fragments[0])
    run_id: UUID = await seed_analysis(decision_stores, first, original)
    await prepare_questions(decision_stores, run_id, first, original)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        await store.answer(run_id, view.questions[0].id, answer_command(view.questions[0]))
    second: ParsedDocument = document(
        first.file_id, "Хранить отчёты 7 дней, только для администратора."
    )
    current: RequirementView = referenced_requirement(second, second.fragments[0])
    next_id: UUID = await seed_analysis(decision_stores, second, current, run_id)
    await prepare_questions(decision_stores, next_id, second, current, changed_basis=flag)
    async with decision_stores.open() as store:
        updated: ClarificationView = await store.get(next_id)
        assert updated.questions[0].revision == 2
        assert updated.questions[0].status == "open"
        assert updated.questions[0].previous_basis is not None
        assert "Повторить запрос" not in updated.requirements[0].normalized_text
        assert updated.questions[0].sources[0].quote == second.fragments[0].text


async def test_unrelated_paragraph_edit_keeps_applicable_answer(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    first: ParsedDocument = document(uuid4(), "Хранить отчёты 30 дней.")
    other: DocumentFragment = replace(first.fragments[0], fragment_id=uuid4(), text="Цвет синий.")
    first = replace(first, fragments=(*first.fragments, other))
    original: RequirementView = referenced_requirement(first, first.fragments[0])
    run_id: UUID = await seed_analysis(decision_stores, first, original)
    await prepare_questions(decision_stores, run_id, first, original)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        await store.answer(run_id, view.questions[0].id, answer_command(view.questions[0]))
    second: ParsedDocument = document(first.file_id, first.fragments[0].text)
    second = replace(second, fragments=(*second.fragments, replace(other, text="Цвет зелёный.")))
    current: RequirementView = referenced_requirement(second, second.fragments[0])
    next_id: UUID = await seed_analysis(decision_stores, second, current, run_id)
    await prepare_questions(decision_stores, next_id, second, current)
    async with decision_stores.open() as store:
        updated: ClarificationView = await store.get(next_id)
        assert updated.questions[0].revision == 1
        assert updated.questions[0].status == "answered"
        assert "Повторить запрос" in updated.requirements[0].normalized_text


async def test_changed_dependent_statement_cannot_inherit_answer_from_same_fragment(
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
    current: RequirementView = referenced_requirement(source, source.fragments[0])
    current.original_text = current.normalized_text = "Для администратора 7 дней."
    next_id: UUID = await seed_analysis(decision_stores, source, current, run_id)
    await prepare_questions(decision_stores, next_id, source, current, changed_basis=False)
    async with decision_stores.open() as store:
        updated: ClarificationView = await store.get(next_id)
        assert updated.questions[0].revision == 2
        assert "Повторить запрос" not in updated.requirements[0].normalized_text

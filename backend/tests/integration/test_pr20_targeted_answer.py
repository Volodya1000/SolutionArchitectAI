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
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
    RequirementView,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize("reverse", [False, True])
async def test_answer_updates_only_target_condition_from_shared_fragment(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore], reverse: bool
) -> None:
    source: ParsedDocument = document(uuid4(), "Хранить отчёты 30 дней. Доступ требует уточнения.")
    first: RequirementView = referenced_requirement(source, source.fragments[0])
    first.original_text = first.normalized_text = "Хранить отчёты 30 дней."
    second: RequirementView = referenced_requirement(source, source.fragments[0])
    second.original_text = second.normalized_text = "Доступ требует уточнения."
    run_id: UUID = await seed_analysis(decision_stores, source, second)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        row: ExtractionRow = await store.extraction(run_id)
        snapshot: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        snapshot.requirements = [second, first] if reverse else [first, second]
        row.snapshot_json = snapshot.model_dump_json()
    await prepare_questions(decision_stores, run_id, source, second)
    async with decision_stores.open() as store:
        before: ClarificationView = await store.get(run_id)
        await store.answer(run_id, before.questions[0].id, answer_command(before.questions[0]))
    async with decision_stores.open() as store:
        after: ClarificationView = await store.get(run_id)
        actual: dict[UUID, RequirementView] = {item.id: item for item in after.requirements}
        assert actual[first.id] == first
        assert actual[second.id].normalized_text.endswith("Повторить запрос")
        assert actual[second.id].sources == second.sources

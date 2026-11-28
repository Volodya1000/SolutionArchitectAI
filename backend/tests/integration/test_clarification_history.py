from dataclasses import replace
from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.clarification_graph import install_questions
from backend.test_helpers.clarification_history import (
    answer_command,
    prepare_questions,
    seed_analysis,
)
from backend.test_helpers.clarification_models import referenced_requirement
from backend.test_helpers.document_builders import ORIGINAL, document
from backend.test_helpers.extraction_resources import ExtractionResources, upload
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
    RequirementView,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.domain.documents import (
    ParsedDocument,
)
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def first_analysis(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    *,
    answered: bool = True,
) -> tuple[UUID, ParsedDocument, RequirementView]:
    source: ParsedDocument = document(uuid4())
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    run_id: UUID = await seed_analysis(stores, source, requirement)
    await prepare_questions(stores, run_id, source, requirement)
    store: SqlAlchemyClarificationStore
    if answered:
        async with stores.open() as store:
            question: ClarificationQuestion = (await store.get(run_id)).questions[0]
            await store.answer(run_id, question.id, answer_command(question))
    return run_id, source, requirement


async def test_reused_open_question_binds_current_version_and_accepts_answer(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    first_id: UUID
    first_source: ParsedDocument
    _first_requirement: RequirementView
    first_id, first_source, _first_requirement = await first_analysis(
        decision_stores, answered=False
    )
    current_source: ParsedDocument = document(first_source.file_id)
    current_requirement: RequirementView = referenced_requirement(
        current_source, current_source.fragments[0]
    )
    second_id: UUID = await seed_analysis(
        decision_stores, current_source, current_requirement, first_id
    )
    await prepare_questions(decision_stores, second_id, current_source, current_requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        question: ClarificationQuestion = (await store.get(second_id)).questions[0]
        assert question.sources[0].version_id == current_source.version_id
        command: AnswerClarification = answer_command(question)
        assert await store.preflight_answer(second_id, question.id, command) is None
        decision: DecisionResult = await store.answer(second_id, question.id, command)
        assert decision.requirement_ids == [current_requirement.id]
        assert decision.source_versions == command.source_versions
    async with decision_stores.open() as store:
        first: ClarificationView = await store.get(first_id)
        second: ClarificationView = await store.get(second_id)
        assert first.questions[0].sources[0].version_id == first_source.version_id
        assert second.requirements[0].normalized_text == ORIGINAL + "\n" + "Повторить запрос"


@pytest.mark.parametrize("new_version", [False, True])
async def test_empty_agent_result_carries_applicable_answer_and_preserves_origin(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    new_version: bool,
) -> None:
    first_id: UUID
    source: ParsedDocument
    original_requirement: RequirementView
    first_id, source, original_requirement = await first_analysis(decision_stores)
    current_source: ParsedDocument = document(source.file_id) if new_version else source
    current_requirement: RequirementView = referenced_requirement(
        current_source, current_source.fragments[0]
    )
    second_id: UUID = await seed_analysis(
        decision_stores, current_source, current_requirement, first_id
    )
    await prepare_questions(
        decision_stores, second_id, current_source, current_requirement, candidate=False
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(second_id)
        assert view.requirements[0].normalized_text == ORIGINAL + "\n" + "Повторить запрос"
        assert len(view.questions) == 1
        assert view.questions[0].status == "answered"
        assert view.questions[0].requirement_ids == [current_requirement.id]
        assert view.questions[0].sources[0].version_id == current_source.version_id
        assert view.decisions[0].run_id == first_id
        assert view.decisions[0].requirement_ids == [original_requirement.id]
        assert view.decisions[0].source_versions == [
            SourceVersion(version_id=source.version_id, sha256=source.sha256)
        ]


async def test_reused_decision_keeps_origin_requirement_ids(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    first_id: UUID
    source: ParsedDocument
    original_requirement: RequirementView
    first_id, source, original_requirement = await first_analysis(decision_stores)
    current_requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    second_id: UUID = await seed_analysis(decision_stores, source, current_requirement, first_id)
    await prepare_questions(decision_stores, second_id, source, current_requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(second_id)
        assert view.decisions[0].requirement_ids == [original_requirement.id]
        assert view.requirements[0].normalized_text == ORIGINAL + "\n" + "Повторить запрос"


async def test_old_analysis_excludes_future_revision_decisions(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    first_id: UUID
    source: ParsedDocument
    _original_requirement: RequirementView
    first_id, source, _original_requirement = await first_analysis(decision_stores)
    changed_source: ParsedDocument = document(
        source.file_id, "Система должна удалять отчёты через день."
    )
    requirement: RequirementView = referenced_requirement(
        changed_source, changed_source.fragments[0]
    )
    second_id: UUID = await seed_analysis(decision_stores, changed_source, requirement, first_id)
    await prepare_questions(
        decision_stores, second_id, changed_source, requirement, changed_basis=True
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        question: ClarificationQuestion = (await store.get(second_id)).questions[0]
        assert question.revision == 2
        await store.answer(second_id, question.id, answer_command(question, "Удалять без повторов"))
    async with decision_stores.open() as store:
        original: ClarificationView = await store.get(first_id)
        assert original.questions[0].revision == 1
        assert [decision.text for decision in original.decisions] == ["Повторить запрос"]


async def test_empty_agent_result_does_not_carry_answer_to_changed_evidence(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    first_id: UUID
    source: ParsedDocument
    _original_requirement: RequirementView
    first_id, source, _original_requirement = await first_analysis(decision_stores)
    changed_source: ParsedDocument = document(
        source.file_id, ORIGINAL + " Источник изменил условия."
    )
    requirement: RequirementView = referenced_requirement(
        changed_source, changed_source.fragments[0]
    )
    requirement.original_text, requirement.normalized_text = ORIGINAL, ORIGINAL
    requirement.sources[0].quote = ORIGINAL
    second_id: UUID = await seed_analysis(decision_stores, changed_source, requirement, first_id)
    await prepare_questions(
        decision_stores, second_id, changed_source, requirement, candidate=False
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(second_id)
        assert view.decisions == []
        assert view.requirements[0].normalized_text == ORIGINAL


@pytest.mark.parametrize("surrounding_changed", [False, True])
async def test_explicit_changed_basis_checks_full_fragment_even_when_quote_is_unchanged(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore], surrounding_changed: bool
) -> None:
    first_id: UUID
    source: ParsedDocument
    _original_requirement: RequirementView
    first_id, source, _original_requirement = await first_analysis(decision_stores)
    text: str = ORIGINAL + " Surrounding policy changed." if surrounding_changed else ORIGINAL
    current_source: ParsedDocument = document(source.file_id, text)
    requirement: RequirementView = referenced_requirement(
        current_source, current_source.fragments[0]
    )
    requirement.original_text, requirement.normalized_text = ORIGINAL, ORIGINAL
    requirement.sources[0].quote = ORIGINAL
    second_id: UUID = await seed_analysis(decision_stores, current_source, requirement, first_id)
    await prepare_questions(
        decision_stores, second_id, current_source, requirement, changed_basis=True
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(second_id)
        assert view.questions[0].revision == (2 if surrounding_changed else 1)
        assert view.questions[0].status == ("open" if surrounding_changed else "answered")
        assert view.questions[0].previous_basis == ("Нет условия" if surrounding_changed else None)
        if surrounding_changed:
            assert view.requirements[0].normalized_text == ORIGINAL


async def test_different_quote_of_unchanged_fragment_does_not_reopen_closed_question(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    source: ParsedDocument = document(uuid4())
    original_requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    original_requirement.sources[0].quote = "Система должна"
    first_id: UUID = await seed_analysis(decision_stores, source, original_requirement)
    await prepare_questions(decision_stores, first_id, source, original_requirement)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        question: ClarificationQuestion = (await store.get(first_id)).questions[0]
        await store.answer(first_id, question.id, answer_command(question))
    current_source: ParsedDocument = replace(document(source.file_id), sha256=source.sha256)
    current_requirement: RequirementView = referenced_requirement(
        current_source, current_source.fragments[0]
    )
    current_requirement.sources[0].quote = "хранить отчёты."
    second_id: UUID = await seed_analysis(
        decision_stores, current_source, current_requirement, first_id
    )
    await prepare_questions(
        decision_stores, second_id, current_source, current_requirement, changed_basis=True
    )
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(second_id)
        assert view.questions[0].revision == 1
        assert view.questions[0].status == "answered"
        assert view.questions[0].previous_basis is None


async def test_answer_in_shared_history_resumes_other_waiting_analysis(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> None:
    await install_questions(resources, monkeypatch, count=1)
    source: DocumentVersionView = await upload(resources)
    first: ExtractionView = await resources.service.start(
        ExtractionStart(
            operation_id=uuid4(), version_ids=[source.version_id], answer_history_mode="new"
        )
    )
    resources.runs.append(first.id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    service: ClarificationService = await resources.container.get(ClarificationService)
    await worker.execute(first.id)
    second: ExtractionView = await resources.service.start(
        ExtractionStart(
            operation_id=uuid4(), version_ids=[source.version_id], answer_history_id=first.id
        )
    )
    resources.runs.append(second.id)
    await worker.execute(second.id)
    first_before: ExtractionView = await resources.view(first.id)
    second_view: ClarificationView = await service.get(second.id)
    question: ClarificationQuestion = second_view.questions[0]
    await service.answer(second.id, question.id, answer_command(question))
    store: ExtractionStore
    async with resources.stores.open() as store:
        assert first.id in {run.id for run in await store.pending()}
    await worker.execute(first.id)
    first_after: ExtractionView = await resources.view(first.id)
    assert first_after.status == RunStatus.COMPLETED
    assert first_after.requests == first_before.requests

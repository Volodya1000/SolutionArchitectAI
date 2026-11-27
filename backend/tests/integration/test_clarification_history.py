import json
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.tests.integration.test_clarification_commands import (  # pylint: disable=unused-import,useless-import-alias
    decision_stores_fixture as decision_stores_fixture,
)
from backend.tests.integration.test_clarification_graph import install_questions
from backend.tests.integration.test_extraction_lifecycle import ExtractionResources, upload
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from backend.tests.unit.test_clarification_agent import ClarificationModel, referenced_requirement
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContext,
    ClarificationContextBuilder,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    RequirementView,
    StoredModelProfile,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.persistence.clarifications.clarification_factory import (
    SqlAlchemyClarificationStoreFactory,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]
ORIGINAL: Final[str] = "Система должна хранить отчёты."


def document(file_id: UUID, text: str = ORIGINAL) -> ParsedDocument:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(), text, SourceLocator(LocatorKind.LINES, 1, 1)
    )
    return ParsedDocument(file_id, uuid4(), uuid4().hex * 2, "test", text, (fragment,))


async def seed_analysis(
    stores: SqlAlchemyClarificationStoreFactory,
    source: ParsedDocument,
    requirement: RequirementView,
    history_id: UUID | None = None,
) -> UUID:
    run_id: UUID = uuid4()
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(),
        version_ids=[source.version_id],
        answer_history_mode="new" if history_id is None else "reuse",
        answer_history_id=history_id,
    )
    profile: StoredModelProfile = StoredModelProfile.model_validate(
        LLMSettings().model_dump(exclude={"api_key"})
    )
    snapshot: ExtractionView = ExtractionView(
        id=run_id,
        status=RunStatus.WAITING_INPUT,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model="fake-chat",
        model_profile=profile,
        coverage=CoverageView(),
        contract_version="test",
        prompt_version="test",
        requirements=[requirement],
        version_ids=[source.version_id],
    )
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        store.session.add(
            ExtractionRow(
                id=run_id,
                task_id=stores.actor.task_id,
                operation_id=command.operation_id,
                payload_digest="test",
                config_digest="test",
                command_json=command.model_dump_json(),
                snapshot_json=snapshot.model_dump_json(),
                status=snapshot.status.value,
                created_at=snapshot.created_at,
            )
        )
    return run_id


async def prepare_questions(
    stores: SqlAlchemyClarificationStoreFactory,
    run_id: UUID,
    source: ParsedDocument,
    requirement: RequirementView,
    *,
    candidate: bool = True,
    changed_basis: bool = False,
) -> None:
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        history: list[ClarificationQuestion] = await store.history(run_id)
        decisions: list[DecisionResult] = await store.history_decisions(run_id)
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        history,
        decisions,
        ModelProfile("test", StructuredMode.JSON_TEXT, 64000, 4096),
    )
    payload: dict[str, object] = {
        "questions": [
            {
                "gap_key": history[0].gap_key if history else "reports:failure",
                "text": "Как обрабатывать отказ?",
                "basis": "Условие изменилось" if changed_basis else "Нет условия",
                "dependent_decision": "Обработка отказа",
                "blocking": True,
                "requirement_ids": ["r0"],
                "evidence": [{"fragment_id": "f0", "quote": requirement.sources[0].quote}],
                "changed_basis": changed_basis,
            }
        ]
        if candidate
        else []
    }
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        ClarificationModel(json.dumps(payload)),
        GenerationPolicy(1, 10, 0, 1, 0, 60000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    questions: list[ClarificationQuestion] = await ClarificationAgent(generator).clarify(
        context,
        ExecutionBudget(1, monotonic() + 10, 5, correction_retries=0),
    )
    async with stores.open() as store:
        await store.save_questions(run_id, questions)


def answer_command(
    question: ClarificationQuestion, text: str = "Повторить запрос"
) -> AnswerClarification:
    return AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=question.revision,
        source_versions=[
            SourceVersion(version_id=source.version_id, sha256=source.sha256)
            for source in question.sources
            if source.version_id and source.sha256
        ],
        kind="answer",
        text=text,
        basis="Решение архитектора",
    )


async def first_analysis(
    stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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
    decision_stores: SqlAlchemyClarificationStoreFactory, surrounding_changed: bool
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
    decision_stores: SqlAlchemyClarificationStoreFactory,
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

from datetime import UTC, datetime
from time import monotonic
from typing import Final
from uuid import uuid4

import pytest
from pydantic import BaseModel

from backend.test_helpers.bounded_review_model import CrossSectionModel
from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
    ClarificationPayload,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    ClarificationReviewCoverage,
    DecisionResult,
)
from solution_architect_ai.application.models.clarification_review_models import (
    ClarificationReviewResult,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.clarification_review import ClarificationReview
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


async def test_long_brd_cross_section_answer_is_reviewed_without_oversize_request() -> None:
    fragments: tuple[DocumentFragment, ...] = tuple(
        DocumentFragment(uuid4(), text, SourceLocator(LocatorKind.LINES, index + 1, index + 1))
        for index, text in enumerate(
            [
                "Доступ требует уточнения.",
                *["Справочные сведения. " * 40 for _ in range(18)],
                "При отказе отклонить запрос.",
            ]
        )
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(),
        uuid4(),
        "a" * 64,
        "test",
        "\n".join(fragment.text for fragment in fragments),
        fragments,
    )
    adapter: CrossSectionModel = CrossSectionModel()
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        adapter,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [referenced_requirement(document, fragments[0])],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(100, monotonic() + 60, 10, correction_retries=0))
    assert result.questions == []
    assert result.coverage.complete
    assert result.coverage.reviewed_fragments == len(fragments)
    assert len(adapter.requests) > 2
    assert all(
        ClarificationPayload.model_validate_json(
            request.messages[-1].content
        ).coverage.omitted_fragment_count
        for request, schema in zip(adapter.requests, adapter.schemas, strict=True)
        if schema is ClarificationSet
    )
    request: StructuredRequest
    schema: type[BaseModel]
    for request, schema in zip(adapter.requests, adapter.schemas, strict=True):
        await generator.check_context(request, schema)


async def test_growing_answer_history_is_windowed_and_accounted_for() -> None:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(), "Доступ требует уточнения.", SourceLocator(LocatorKind.LINES, 1, 1)
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", fragment.text, (fragment,)
    )
    requirement: RequirementView = referenced_requirement(document, fragment)
    history: list[ClarificationQuestion] = [
        ClarificationQuestion(
            id=uuid4(),
            gap_key=f"past:{index}",
            text="Прежний вопрос " * 40,
            basis="Ранее принятое решение",
            dependent_decision="Реализация",
            blocking=False,
            requirement_ids=[requirement.id],
            sources=requirement.sources,
            status="answered",
        )
        for index in range(20)
    ]
    decisions: list[DecisionResult] = [
        DecisionResult(
            operation_id=uuid4(),
            run_id=uuid4(),
            question_id=question.id,
            question_revision=1,
            decision_id=uuid4(),
            kind="answer",
            text="Согласованное условие " * 60,
            basis="Архитектор",
            author_id=uuid4(),
            author="Автор",
            created_at=datetime.now(UTC),
            requirement_ids=[requirement.id],
        )
        for question in history
    ]
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [requirement],
        history,
        decisions,
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    adapter: CrossSectionModel = CrossSectionModel()
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        adapter,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(100, monotonic() + 60, 10, correction_retries=0))
    assert result.coverage.complete
    assert result.coverage.total_history == result.coverage.reviewed_history == 20
    assert result.coverage.unreviewed_question_ids == []
    assert len(adapter.requests) > 1
    assert any(
        ClarificationPayload.model_validate_json(
            request.messages[-1].content
        ).coverage.omitted_history_records
        > 0
        for request, schema in zip(adapter.requests, adapter.schemas, strict=True)
        if schema is ClarificationSet
    )


@pytest.mark.parametrize("requests", [0, 1])
async def test_incomplete_review_reports_unvisited_sources_before_budget_failure(
    requests: int,
) -> None:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(), "Доступ требует уточнения.", SourceLocator(LocatorKind.LINES, 1, 1)
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", fragment.text, (fragment,)
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [referenced_requirement(document, fragment)],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512),
    )
    adapter: ClarificationModel = ClarificationModel("not JSON")
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        adapter,
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    progress: list[ClarificationReviewCoverage] = []

    async def observe(coverage: ClarificationReviewCoverage) -> None:
        progress.append(coverage.model_copy(deep=True))

    failure: pytest.ExceptionInfo[StructuredGenerationFailure]
    with pytest.raises(StructuredGenerationFailure) as failure:
        await ClarificationReview(ClarificationAgent(generator)).run(
            context, ExecutionBudget(requests, monotonic() + 60, 10, correction_retries=0), observe
        )
    assert failure.value.reason == (
        StructuredErrorCode.BUDGET_EXHAUSTED if requests == 0 else StructuredErrorCode.JSON_INVALID
    )
    assert progress[-1].model_requests == requests
    assert not progress[-1].complete
    assert progress[-1].unreviewed_fragment_ids == [str(fragment.fragment_id)]


async def test_same_window_explicit_answer_removes_a_false_proposed_gap() -> None:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(),
        "Доступ требует уточнения. При отказе отклонить запрос.",
        SourceLocator(LocatorKind.LINES, 1, 1),
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", fragment.text, (fragment,)
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [referenced_requirement(document, fragment)],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        CrossSectionModel(),
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(100, monotonic() + 60, 10, correction_retries=0))
    assert result.questions == []
    assert result.coverage.complete


async def test_omission_metadata_does_not_grow_with_thousands_of_source_identifiers() -> None:
    fragments: tuple[DocumentFragment, ...] = tuple(
        DocumentFragment(
            uuid4(), "Справочные сведения.", SourceLocator(LocatorKind.LINES, index + 1, index + 1)
        )
        for index in range(1000)
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(),
        uuid4(),
        "a" * 64,
        "test",
        "\n".join(fragment.text for fragment in fragments),
        fragments,
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [referenced_requirement(document, fragments[0])],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        CrossSectionModel(),
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    windows: list[ClarificationContext] = await ClarificationContextPlanner(generator, 0).plan(
        context
    )
    assert len(windows) > 1
    assert max(len(window.part.messages[-1].content) for window in windows) < 8000


async def test_source_restatement_cannot_remove_an_established_contradiction() -> None:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(),
        "Доступ требует уточнения. При отказе отклонить запрос.",
        SourceLocator(LocatorKind.LINES, 1, 1),
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", fragment.text, (fragment,)
    )
    requirement: RequirementView = referenced_requirement(document, fragment)
    requirement.category = RequirementCategory.CONTRADICTION
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [requirement],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        CrossSectionModel(),
        GenerationPolicy(1, 60, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(100, monotonic() + 60, 10, correction_retries=0))
    assert len(result.questions) == 1
    assert result.questions[0].mandatory_conflict == requirement.normalized_text
    assert result.questions[0].blocks_completion

import json
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Final
from uuid import uuid4

import pytest
from pydantic import BaseModel, TypeAdapter

from backend.tests.integration.test_clarification_history import document
from backend.tests.unit.test_clarification_agent import referenced_requirement
from backend.tests.unit.test_pr20_bounded_review import CrossSectionModel
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_history_matcher import (
    ClarificationHistoryMatcher,
)
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.context.source_fingerprints import (
    fragment_fingerprints,
    requirement_fingerprint,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
    ClarificationPayload,
    DecisionHistoryContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    DecisionResult,
)
from solution_architect_ai.application.models.clarification_review_models import (
    ClarificationReviewResult,
    SourceReviewVerdict,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.clarification_review_validation import (
    validate_source_review,
)
from solution_architect_ai.application.workflows.clarification_review import ClarificationReview
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio
SAVED_ANSWER: Final[str] = "При отказе отклонить запрос."


class PagedHistoryModel(CrossSectionModel):
    async def invoke[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResponse[T]:
        body: dict[str, object] = TypeAdapter(dict[str, object]).validate_json(
            request.messages[-1].content
        )
        if body["role"] == "clarification_review":
            decisions: list[DecisionHistoryContext] = TypeAdapter(
                list[DecisionHistoryContext]
            ).validate_python(body.get("decisions", []))
            answers: list[DecisionHistoryContext] = [
                decision for decision in decisions if decision.text == SAVED_ANSWER
            ]
            self.requests.append(request)
            self.schemas.append(schema)
            return StructuredResponse(
                json.dumps(
                    {
                        "resolved": bool(answers),
                        "reason": "Ответ зафиксирован архитектором"
                        if answers
                        else "Нет ответа в этой части истории",
                        "evidence": [],
                        "answer_decision_ids": [decision.decision_id.hex for decision in answers],
                    }
                ),
                "stop",
            )
        payload: ClarificationPayload = ClarificationPayload.model_validate_json(
            request.messages[-1].content
        )
        if any(decision.text == SAVED_ANSWER for decision in payload.decisions):
            self.requests.append(request)
            self.schemas.append(schema)
            return StructuredResponse('{"questions": []}', "stop")
        return await super().invoke(request, schema)


async def test_saved_answer_on_another_history_page_removes_false_blocker() -> None:
    source: ParsedDocument = document(uuid4(), "Доступ требует уточнения.")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    fingerprint_context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
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
            source_fingerprints=fragment_fingerprints(fingerprint_context.part.fragments),
            requirement_fingerprints={requirement.id: requirement_fingerprint(requirement)},
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
            text=SAVED_ANSWER if index == 19 else "Иное согласованное условие " * 60,
            basis="Архитектор",
            author_id=uuid4(),
            author="Автор",
            created_at=datetime.now(UTC),
            requirement_ids=[requirement.id],
        )
        for index, question in enumerate(history)
    ]
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        history,
        decisions,
        ModelProfile("test", StructuredMode.JSON_TEXT, 4800, 512, 128),
    )
    model: PagedHistoryModel = PagedHistoryModel()
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 60, 0, 100, 0, 1000), LangChainTokenCounter(2, chat_prompt=False)
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(100, monotonic() + 60, 10, correction_retries=0))
    assert not any(question.status == "open" for question in result.questions)
    assert result.coverage.complete
    assert result.coverage.reviewed_history == 20


def test_history_review_rejects_superseded_answer_revision() -> None:
    source: ParsedDocument = document(uuid4(), "Доступ требует уточнения.")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    fingerprint_context: ClarificationContext = ClarificationContextBuilder().build(
        (source,), [requirement], [], [], ModelProfile("test", StructuredMode.JSON_TEXT, 16000, 512)
    )
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="access:failure",
        revision=2,
        text="Как реагировать на отказ?",
        basis="Условие изменилось",
        dependent_decision="Проверка доступа",
        blocking=True,
        requirement_ids=[requirement.id],
        sources=requirement.sources,
        status="answered",
        source_fingerprints=fragment_fingerprints(fingerprint_context.part.fragments),
        requirement_fingerprints={requirement.id: requirement_fingerprint(requirement)},
    )
    superseded: DecisionResult = DecisionResult(
        operation_id=uuid4(),
        run_id=uuid4(),
        question_id=question.id,
        question_revision=1,
        decision_id=uuid4(),
        kind="answer",
        text=SAVED_ANSWER,
        basis="Предыдущее основание",
        author_id=uuid4(),
        author="Архитектор",
        created_at=datetime.now(UTC),
        requirement_ids=[requirement.id],
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        [question],
        [superseded],
        ModelProfile("test", StructuredMode.JSON_TEXT, 16000, 512),
    )
    verdict: SourceReviewVerdict = SourceReviewVerdict(
        resolved=True,
        reason="Ссылка на прежнее решение",
        answer_decision_ids=[superseded.decision_id],
    )
    with pytest.raises(ValueError, match=r"unavailable|rejected|superseded|revision|applicable"):
        validate_source_review(verdict, context, question)


@pytest.mark.parametrize("new_version", [False, True])
def test_rebinding_answer_survives_new_chunk_boundaries(new_version: bool) -> None:
    source: ParsedDocument = document(uuid4(), "Retain reports for thirty days.")
    original: RequirementView = referenced_requirement(source, source.fragments[0])
    profile: ModelProfile = ModelProfile("test", StructuredMode.JSON_TEXT, 16000, 512)
    initial: ClarificationContext = ClarificationContextBuilder().build(
        (source,), [original], [], [], profile
    )
    matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(
        initial.part.fragments, (original,)
    )
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="retention:failure",
        text="What happens after retention?",
        basis="The response is not specified",
        dependent_decision="Storage behavior",
        blocking=True,
        requirement_ids=[original.id],
        sources=original.sources,
        status="answered",
        source_fingerprints=matcher.source_fingerprints,
        requirement_fingerprints=matcher.requirement_fingerprints,
    )
    current_source: ParsedDocument = (
        replace(
            source,
            version_id=uuid4(),
            fragments=(replace(source.fragments[0], fragment_id=uuid4()),),
        )
        if new_version
        else source
    )
    current: RequirementView = referenced_requirement(current_source, current_source.fragments[0])
    context: ClarificationContext = ClarificationContextBuilder().build(
        (current_source,), [current], [], [], profile
    )
    whole: ContextFragment = context.part.fragments[0]
    chunks: tuple[ContextFragment, ...] = (
        replace(whole, text=whole.text[:12]),
        replace(whole, text=whole.text[12:], offset=12),
    )
    updated_matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(chunks, (current,))
    assert set(matcher.source_fingerprints.values()) == set(
        updated_matcher.source_fingerprints.values()
    )
    rebound: ClarificationQuestion | None = updated_matcher.rebind(question)
    assert rebound is not None
    assert rebound.status == "answered"
    assert rebound.requirement_ids == [current.id]
    assert rebound.sources[0].quote == "Retain reports for thirty days."
    assert rebound.sources[0].version_id == current_source.version_id
    assert rebound.sources[0].fragment_id == str(current_source.fragments[0].fragment_id)
    assert question.sources[0].version_id == source.version_id

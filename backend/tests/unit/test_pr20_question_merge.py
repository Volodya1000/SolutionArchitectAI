from time import monotonic
from typing import Final
from uuid import uuid4

import pytest

from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_question_merge import (
    merge_question_windows,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.workflows.clarification_review import ClarificationReview
from solution_architect_ai.application.workflows.clarification_review_progress import (
    ClarificationReviewProgress,
)
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize("order", [(0, 1), (1, 0), (0, 1, 0)])
async def test_same_gap_merges_all_requirement_bindings_without_losing_blocker(
    monkeypatch: pytest.MonkeyPatch, order: tuple[int, ...]
) -> None:
    fragments: tuple[DocumentFragment, ...] = tuple(
        DocumentFragment(uuid4(), text, SourceLocator(LocatorKind.LINES, index + 1, index + 1))
        for index, text in enumerate(("First condition.", "Second condition."))
    )
    source: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", "\n".join(item.text for item in fragments), fragments
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [referenced_requirement(source, fragment) for fragment in source.fragments],
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 64000, 4096),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        ClarificationModel('{"questions":[]}'),
        GenerationPolicy(1, 10, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    agent: ClarificationAgent = ClarificationAgent(generator)
    questions: list[ClarificationQuestion] = [
        ClarificationQuestion(
            id=uuid4(),
            gap_key="same-gap",
            text="Resolve condition",
            basis=f"Reason {index}",
            dependent_decision=f"Decision {index}",
            blocking=index == 0,
            requirement_ids=[requirement.id],
            sources=requirement.sources,
            mandatory_conflict="Mandatory conflict" if index == 0 else None,
        )
        for index, requirement in enumerate(context.requirements)
    ]
    sequence: list[ClarificationQuestion] = [questions[index] for index in order]

    async def clarify(
        _context: ClarificationContext, _budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        return [sequence.pop(0)]

    monkeypatch.setattr(agent, "clarify", clarify)
    budget: ExecutionBudget = ExecutionBudget(100, monotonic() + 30, 10)
    merged: list[ClarificationQuestion] = await ClarificationReview(agent).collect_questions(
        [context] * len(order), budget, ClarificationReviewProgress(context, 100, None)
    )
    assert len(merged) == 1
    assert set(merged[0].requirement_ids) == {
        requirement.id for requirement in context.requirements
    }
    assert merged[0].blocking
    assert merged[0].mandatory_conflict == "Mandatory conflict"
    assert merged[0].blocks_completion
    assert {item.quote for item in merged[0].sources} == {item.text for item in source.fragments}
    assert all(question.basis in merged[0].basis for question in questions)
    assert merge_question_windows(questions) == merge_question_windows(list(reversed(questions)))
    assert merge_question_windows(questions) == merge_question_windows([*questions, questions[0]])


def test_merge_preserves_latest_accepted_revision() -> None:
    accepted: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="accepted",
        text="Accepted condition",
        basis="Agreed",
        revision=2,
        dependent_decision="Decision",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
        status="answered",
    )
    old: ClarificationQuestion = accepted.model_copy(update={"revision": 1, "status": "open"})
    assert merge_question_windows([old, accepted, old]) == accepted

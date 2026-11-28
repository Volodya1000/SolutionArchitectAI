from time import monotonic
from uuid import uuid4

import pytest
from pydantic import BaseModel

from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.infrastructure.context import LangChainTokenCounter


class RequirementPayload(BaseModel):
    id: str
    original_text: str
    normalized_text: str
    category: str


class Payload(BaseModel):
    requirements: list[RequirementPayload]


@pytest.mark.anyio
@pytest.mark.parametrize("reverse", [False, True])
async def test_adapter_receives_unambiguous_wording_for_same_fragment(reverse: bool) -> None:
    fragment: DocumentFragment = DocumentFragment(
        uuid4(),
        "Хранить отчёты 30 дней. Доступ к отчётам требует уточнения.",
        SourceLocator(LocatorKind.LINES, 1, 1),
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", fragment.text, (fragment,)
    )
    first: RequirementView = referenced_requirement(document, fragment)
    first.original_text = "Хранить отчёты 30 дней."
    first.normalized_text = "Система сохраняет отчёты в течение 30 дней."
    second: RequirementView = referenced_requirement(document, fragment)
    second.original_text = "Доступ к отчётам требует уточнения."
    second.normalized_text = "Не определены права доступа к отчётам."
    second.category = RequirementCategory.CONSTRAINT
    requirements: list[RequirementView] = [second, first] if reverse else [first, second]
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        requirements,
        [],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 16000, 2048),
    )
    adapter: ClarificationModel = ClarificationModel('{"questions": []}')
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        adapter,
        GenerationPolicy(1, 10, 0, 1, 0, 12000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    await ClarificationAgent(generator).clarify(context, ExecutionBudget(1, monotonic() + 10, 5))
    payload: Payload = Payload.model_validate_json(adapter.requests[0].messages[-1].content)
    expected: dict[str, tuple[str, str, str]] = {
        str(first.id): (
            "functional",
            "Хранить отчёты 30 дней.",
            "Система сохраняет отчёты в течение 30 дней.",
        ),
        str(second.id): (
            "constraint",
            "Доступ к отчётам требует уточнения.",
            "Не определены права доступа к отчётам.",
        ),
    }
    identifiers: list[str] = [context.requirement_aliases[item.id] for item in payload.requirements]
    assert len(payload.requirements) == 2
    assert len(set(identifiers)) == 2
    assert set(identifiers) == set(expected)
    assert {
        context.requirement_aliases[item.id]: (
            item.category,
            item.original_text,
            item.normalized_text,
        )
        for item in payload.requirements
    } == expected

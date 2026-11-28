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
    first.original_text = first.normalized_text = "Хранить отчёты 30 дней."
    second: RequirementView = referenced_requirement(document, fragment)
    second.original_text = second.normalized_text = "Доступ к отчётам требует уточнения."
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
    item: RequirementPayload
    for item in payload.requirements:
        actual: RequirementView = next(
            value for value in requirements if str(value.id) == context.requirement_aliases[item.id]
        )
        assert item.normalized_text == actual.normalized_text
        assert item.category == actual.category.value

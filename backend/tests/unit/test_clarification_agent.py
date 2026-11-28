import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Final
from uuid import uuid4

import pytest

from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.clarification_review_models import (
    ClarificationReviewResult,
)
from solution_architect_ai.application.models.extraction_models import (
    RequirementView,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.markdown_structure import separator_fragment_ids
from solution_architect_ai.application.workflows.clarification_review import ClarificationReview
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    LocatorKind,
    ParsedDocument,
    SourceLocator,
)
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize("fabricate_source", [False, True])
async def test_clarification_receives_all_selected_fragments_and_rejects_fabricated_evidence(
    fabricate_source: bool,
) -> None:
    first: DocumentFragment = DocumentFragment(
        uuid4(), "Хранить сведения 30 дней", SourceLocator(LocatorKind.LINES, 1, 1)
    )
    second: DocumentFragment = DocumentFragment(
        uuid4(), "Выбор дня в окне хранения", SourceLocator(LocatorKind.LINES, 2, 2)
    )
    document: ParsedDocument = ParsedDocument(
        uuid4(), uuid4(), "a" * 64, "test", first.text + second.text, (first, second)
    )
    requirement: RequirementView = RequirementView(
        id=uuid4(),
        category=RequirementCategory.FUNCTIONAL,
        original_text=second.text,
        normalized_text=second.text,
        sources=[],
    )
    model: ClarificationModel = ClarificationModel(
        json.dumps(
            {
                "questions": [
                    {
                        "gap_key": "date:outside-window",
                        "text": "Как реагировать на дату вне окна?",
                        "basis": "Нет поведения",
                        "dependent_decision": "Проверка даты",
                        "blocking": True,
                        "requirement_ids": [str(requirement.id)],
                        "evidence": [
                            {
                                "fragment_id": str(
                                    uuid4() if fabricate_source else second.fragment_id
                                ),
                                "quote": second.text,
                            }
                        ],
                    }
                ]
            }
        )
    )
    profile: ModelProfile = ModelProfile("test", StructuredMode.JSON_TEXT, 16000, 2048)
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 10, 0, 1, 0, 12000), LangChainTokenCounter(2, chat_prompt=False)
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,), [requirement], [], [], profile
    )
    budget: ExecutionBudget = ExecutionBudget(1, monotonic() + 10, 5, correction_retries=0)
    if fabricate_source:
        with pytest.raises(StructuredGenerationFailure):
            await ClarificationAgent(generator).clarify(context, budget)
    else:
        questions: list[ClarificationQuestion] = await ClarificationAgent(generator).clarify(
            context, budget
        )
        assert len(questions) == 1
        assert questions[0].sources[0].version_id == document.version_id
        assert questions[0].requirement_ids == [requirement.id]
    assert first.text in model.requests[0].messages[-1].content
    assert second.text in model.requests[0].messages[-1].content


async def test_full_reporting_source_and_registry_fit_loaded_model_context_without_omission() -> (
    None
):
    source: Path = Path(__file__).parents[3] / "docs/examples/pr3/reporting-system-complete.md"
    content: bytes = await asyncio.to_thread(source.read_bytes)
    document: ParsedDocument = await asyncio.to_thread(
        DocumentParser().parse, uuid4(), uuid4(), content, source.name, "text/markdown"
    )
    requirements: list[RequirementView] = [
        referenced_requirement(document, fragment)
        for fragment in document.fragments
        if str(fragment.fragment_id) not in separator_fragment_ids(document)
    ]
    profile: ModelProfile = ModelProfile(
        "test", StructuredMode.NATIVE_JSON_SCHEMA, 12288, 6912, 256
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,), requirements, [], [], profile
    )
    model: ClarificationModel = ClarificationModel('{"questions": []}')
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        model, GenerationPolicy(1, 10, 0, 1, 0, 5120), LangChainTokenCounter(2, chat_prompt=False)
    )
    result: ClarificationReviewResult = await ClarificationReview(
        ClarificationAgent(generator)
    ).run(context, ExecutionBudget(128, monotonic() + 10, 5, correction_retries=0))
    assert result.questions == []
    assert result.coverage.complete
    assert result.coverage.reviewed_fragments == len(context.part.fragments)
    assert len(context.part.fragments) == len(document.fragments) - len(
        separator_fragment_ids(document)
    )

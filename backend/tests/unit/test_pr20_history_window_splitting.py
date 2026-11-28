from dataclasses import replace
from typing import Final
from uuid import uuid4

import pytest

from backend.test_helpers.clarification_models import ClarificationModel, referenced_requirement
from backend.test_helpers.document_builders import document
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    CORRECTION_RESERVATION,
    render_messages,
    token_messages,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize("corrections", [0, 2])
async def test_one_history_record_retries_with_source_halves_and_measured_final_messages(
    corrections: int,
) -> None:
    source: ParsedDocument = document(uuid4(), "Source condition. " * 200)
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    requirement.original_text = requirement.normalized_text = "Source condition."
    requirement.sources[0].quote = "Source condition."
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="history",
        text="Previous question " * 70,
        basis="Accepted source condition",
        dependent_decision="Decision",
        blocking=False,
        requirement_ids=[requirement.id],
        sources=requirement.sources,
        status="answered",
    )
    original: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        [question],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 64000, 512),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        ClarificationModel('{"questions":[]}'),
        GenerationPolicy(1, 10, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    planner: ClarificationContextPlanner = ClarificationContextPlanner(generator, corrections)
    fragment: ContextFragment = original.part.fragments[0]
    half: ContextFragment = replace(fragment, text=fragment.text[: len(fragment.text) // 2])
    no_history: ClarificationContext = planner.build(original, (fragment,), [requirement], [])
    half_history: ClarificationContext = planner.build(original, (half,), [requirement], [question])
    estimates: list[int] = [
        generator.token_counter.count(
            token_messages(
                render_messages(
                    StructuredRequest(
                        (
                            *item.part.messages,
                            *(
                                (StructuredMessage(MessageRole.USER, CORRECTION_RESERVATION),)
                                * corrections
                            ),
                        ),
                        item.profile,
                    ),
                    ClarificationSet,
                    include_native_schema=True,
                )
            )
        )
        for item in (no_history, half_history)
    ]
    profile: ModelProfile = replace(original.profile, context_window=max(estimates) + 512 + 20)
    original = replace(original, profile=profile)
    assert await planner.fits(planner.build(original, (fragment,), [requirement], []))
    assert not await planner.fits(original)
    windows: list[ClarificationContext] = await planner.plan(original)
    assert len(windows) >= 2
    assert all(window.payload.history[0].id == question.id for window in windows)
    assert "".join(window.part.fragments[0].text for window in windows) == fragment.text
    assert all(question.id == window.history[0].id for window in windows)
    window: ClarificationContext
    for window in windows:
        await generator.check_context(
            StructuredRequest(
                (
                    *window.part.messages,
                    *((StructuredMessage(MessageRole.USER, CORRECTION_RESERVATION),) * corrections),
                ),
                profile,
            ),
            ClarificationSet,
        )


async def test_indivisible_history_record_is_reported_as_context_too_large() -> None:
    source: ParsedDocument = document(uuid4(), "Source")
    requirement: RequirementView = referenced_requirement(source, source.fragments[0])
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="huge",
        text="Large historical record. " * 500,
        basis="Original basis",
        dependent_decision="Decision",
        blocking=False,
        requirement_ids=[requirement.id],
        sources=requirement.sources,
        status="answered",
    )
    original: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        [question],
        [],
        ModelProfile("test", StructuredMode.JSON_TEXT, 5000, 512),
    )
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        ClarificationModel('{"questions":[]}'),
        GenerationPolicy(1, 10, 0, 100, 0, 1000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    with pytest.raises(StructuredGenerationFailure, match="context_too_large"):
        await ClarificationContextPlanner(generator, 0).plan(original)

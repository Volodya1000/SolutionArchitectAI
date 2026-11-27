from uuid import uuid4

import pytest
from pydantic import BaseModel

from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.clarification_context_planner import (
    ClarificationContextPlanner,
)
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    render_messages,
    token_messages,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser


class NoGenerationModel:
    async def invoke[T: BaseModel](
        self, _request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        raise AssertionError("Planning must not invoke the model")


def context_with_full_output_reserve() -> ClarificationContext:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(),
        uuid4(),
        ("The service shall retain audit entries.\n" * 150).encode(),
        "requirements.md",
        "text/markdown",
    )
    profile: ModelProfile = ModelProfile(
        "fake", StructuredMode.NATIVE_JSON_SCHEMA, 12288, 6912, 256
    )
    return ClarificationContextBuilder().build((document,), [], [], [], profile)


def test_clarification_preserves_the_selected_model_output_limit() -> None:
    context: ClarificationContext = context_with_full_output_reserve()

    assert context.profile.output_limit == 6912


@pytest.mark.anyio
async def test_window_planner_reserves_the_full_configured_response_budget() -> None:
    context: ClarificationContext = context_with_full_output_reserve()
    counter: LangChainTokenCounter = LangChainTokenCounter(2, chat_prompt=False)
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        NoGenerationModel(), GenerationPolicy(1, 60, 2, 10, 0, 5120), counter
    )
    windows: list[ClarificationContext] = await ClarificationContextPlanner(generator, 2).plan(
        context
    )

    assert len(windows) > 1
    window: ClarificationContext
    for window in windows:
        reserved_input: int = counter.count(
            token_messages(
                render_messages(
                    StructuredRequest(window.part.messages, window.profile),
                    ClarificationSet,
                    reserve_corrections=2,
                    include_native_schema=True,
                )
            )
        )
        assert reserved_input + 6912 + 256 <= 12288

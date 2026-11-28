from functools import partial
from uuid import UUID

from solution_architect_ai.application.context.clarification_history_matcher import (
    ClarificationHistoryMatcher,
)
from solution_architect_ai.application.context.clarification_question_builder import build_question
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredRequest,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.clarification_validation import (
    validate_clarifications,
)


class ClarificationAgent:
    def __init__(self, structured_output_generator: StructuredOutputGenerator) -> None:
        self.structured_output_generator: StructuredOutputGenerator = structured_output_generator

    async def clarify(
        self, context: ClarificationContext, budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        payload: ClarificationSet = await self.structured_output_generator.generate(
            StructuredRequest(context.part.messages, context.profile),
            ClarificationSet,
            budget,
            validator=partial(validate_clarifications, context=context),
        )
        questions: list[ClarificationQuestion] = []
        existing: dict[str, ClarificationQuestion] = {
            question.gap_key: question for question in context.history
        }
        matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(
            context.all_fragments or context.part.fragments, context.requirements
        )
        questions = [
            build_question(candidate, context, existing, matcher) for candidate in payload.questions
        ]
        emitted: set[UUID] = {question.id for question in questions}
        previous_question: ClarificationQuestion
        for previous_question in context.history:
            if previous_question.id in emitted or previous_question.status == "open":
                continue
            carried: ClarificationQuestion | None = matcher.rebind(previous_question)
            if carried is not None:
                questions.append(carried)
        return questions

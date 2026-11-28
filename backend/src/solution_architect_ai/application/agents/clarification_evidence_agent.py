from functools import partial

from solution_architect_ai.application.context.clarification_decision_selector import (
    applicable_review_decisions,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
    ContextSource,
    DecisionHistoryContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.clarification_review_models import (
    SourceReviewPayload,
    SourceReviewSubject,
    SourceReviewVerdict,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredMessage,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.clarification_review_prompt import (
    SOURCE_REVIEW_PROMPT,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.application.validation.clarification_review_validation import (
    validate_source_review,
)
from solution_architect_ai.domain.messages import MessageRole


class ClarificationEvidenceAgent:
    def __init__(self, structured_output_generator: StructuredOutputGenerator) -> None:
        self.structured_output_generator: StructuredOutputGenerator = structured_output_generator

    def request(
        self, question: ClarificationQuestion, context: ClarificationContext
    ) -> StructuredRequest:
        aliases: dict[str, str] = {
            identifier: alias for alias, identifier in context.source_aliases.items()
        }
        payload: SourceReviewPayload = SourceReviewPayload(
            question=SourceReviewSubject(
                text=question.text,
                basis=question.basis,
                dependent_decision=question.dependent_decision,
            ),
            fragments=[
                ContextSource(fragment_id=aliases[str(fragment.fragment_id)], text=fragment.text)
                for fragment in context.part.fragments
            ],
            history=context.payload.history,
            decisions=[
                DecisionHistoryContext.from_decision(decision)
                for decision in applicable_review_decisions(context, question)
            ],
        )
        return StructuredRequest(
            (
                StructuredMessage(MessageRole.SYSTEM, SOURCE_REVIEW_PROMPT),
                StructuredMessage(MessageRole.USER, payload.model_dump_json()),
            ),
            context.profile,
        )

    async def review(
        self,
        question: ClarificationQuestion,
        context: ClarificationContext,
        budget: ExecutionBudget,
    ) -> SourceReviewVerdict:
        return await self.structured_output_generator.generate(
            self.request(question, context),
            SourceReviewVerdict,
            budget,
            validator=partial(validate_source_review, context=context, question=question),
        )

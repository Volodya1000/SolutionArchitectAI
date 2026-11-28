from dataclasses import replace
from uuid import UUID

from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.context.source_fingerprints import fragment_fingerprints
from solution_architect_ai.application.errors.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    StructuredMessage,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.structured_prompt import CORRECTION_RESERVATION
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.domain.messages import MessageRole


class ClarificationContextPlanner:
    def __init__(
        self, structured_output_generator: StructuredOutputGenerator, correction_retries: int
    ) -> None:
        self.structured_output_generator: StructuredOutputGenerator = structured_output_generator
        self.correction_retries: int = correction_retries
        self.clarification_context_builder: ClarificationContextBuilder = (
            ClarificationContextBuilder()
        )

    async def fits(self, context: ClarificationContext) -> bool:
        corrections: tuple[StructuredMessage, ...] = (
            StructuredMessage(MessageRole.USER, CORRECTION_RESERVATION),
        ) * self.correction_retries
        try:
            await self.structured_output_generator.check_context(
                StructuredRequest((*context.part.messages, *corrections), context.profile),
                ClarificationSet,
            )
            return True
        except StructuredGenerationFailure as error:
            if error.reason != StructuredErrorCode.CONTEXT_TOO_LARGE:
                raise
            return False

    def build(
        self,
        original: ClarificationContext,
        fragments: tuple[ContextFragment, ...],
        requirements: list[RequirementView],
        history: list[ClarificationQuestion],
    ) -> ClarificationContext:
        history_ids: set[UUID] = {question.id for question in history}
        context: ClarificationContext = self.clarification_context_builder.build_fragments(
            fragments,
            requirements,
            history,
            [decision for decision in original.decisions if decision.question_id in history_ids],
            original.profile,
        )
        complete_fingerprints: dict[str, str] = fragment_fingerprints(
            original.all_fragments or original.part.fragments
        )
        selected_fingerprints: dict[str, str] = fragment_fingerprints(fragments)
        context.payload.coverage.omitted_fragment_count = sum(
            1
            for identifier, fingerprint in complete_fingerprints.items()
            if selected_fingerprints.get(identifier) != fingerprint
        )
        context.payload.coverage.omitted_history_records = sum(
            question.id not in history_ids for question in original.history
        )
        return replace(
            context,
            part=replace(
                context.part,
                messages=(
                    context.part.messages[0],
                    StructuredMessage(MessageRole.USER, context.payload.model_dump_json()),
                ),
            ),
            history=original.history,
            requirements=original.requirements,
            all_fragments=original.all_fragments or original.part.fragments,
        )

    async def source_windows(
        self,
        original: ClarificationContext,
        fragments: tuple[ContextFragment, ...],
        requirements: list[RequirementView],
        history: list[ClarificationQuestion] | None = None,
    ) -> list[ClarificationContext]:
        context: ClarificationContext = self.build(original, fragments, requirements, history or [])
        if await self.fits(context):
            return [context]
        if len(fragments) > 1:
            middle: int = len(fragments) // 2
            result: list[ClarificationContext] = []
            segment: tuple[ContextFragment, ...]
            for segment in (fragments[:middle], fragments[middle:]):
                identifiers: set[str] = {str(fragment.fragment_id) for fragment in segment}
                relevant: list[RequirementView] = [
                    item
                    for item in requirements
                    if any(source.fragment_id in identifiers for source in item.sources)
                ]
                result.extend(await self.source_windows(original, segment, relevant, history))
            return result
        if len(requirements) > 1:
            middle = len(requirements) // 2
            return [
                *await self.source_windows(original, fragments, requirements[:middle], history),
                *await self.source_windows(original, fragments, requirements[middle:], history),
            ]
        fragment: ContextFragment = fragments[0]
        if len(fragment.text) < 256:
            raise StructuredGenerationFailure(StructuredErrorCode.CONTEXT_TOO_LARGE)
        middle = len(fragment.text) // 2
        return [
            *await self.source_windows(
                original, (replace(fragment, text=fragment.text[:middle]),), requirements, history
            ),
            *await self.source_windows(
                original,
                (replace(fragment, text=fragment.text[middle:], offset=fragment.offset + middle),),
                requirements,
                history,
            ),
        ]

    async def history_windows(
        self,
        original: ClarificationContext,
        window: ClarificationContext,
        history: list[ClarificationQuestion],
    ) -> list[ClarificationContext]:
        allowed: frozenset[str] = window.requirement_ids
        requirements: list[RequirementView] = [
            item for item in original.requirements if str(item.id) in allowed
        ]
        context: ClarificationContext = self.build(
            original, window.part.fragments, requirements, history
        )
        if await self.fits(context):
            return [context]
        if len(history) <= 1:
            return await self.source_windows(original, window.part.fragments, requirements, history)
        middle: int = len(history) // 2
        return [
            *await self.history_windows(original, window, history[:middle]),
            *await self.history_windows(original, window, history[middle:]),
        ]

    async def plan(self, original: ClarificationContext) -> list[ClarificationContext]:
        windows: list[ClarificationContext] = await self.source_windows(
            original, original.part.fragments, list(original.requirements)
        )
        result: list[ClarificationContext] = []
        window: ClarificationContext
        for window in windows:
            history: list[ClarificationQuestion] = [
                question
                for question in original.history
                if window.requirement_ids
                or any(
                    source.quote in fragment.text
                    for source in question.sources
                    for fragment in window.part.fragments
                )
            ]
            result.extend(await self.history_windows(original, window, history))
        return result

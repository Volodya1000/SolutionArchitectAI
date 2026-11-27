from types import MappingProxyType
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment, ContextPart
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
    ClarificationPayload,
    ContextCoverage,
    ContextSource,
    DecisionHistoryContext,
    HistoricalSourceContext,
    QuestionHistoryContext,
    RequirementContext,
    RequirementEvidenceContext,
)
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    DecisionResult,
)
from solution_architect_ai.application.models.extraction_models import RequirementView
from solution_architect_ai.application.models.structured_models import (
    ModelProfile,
    StructuredMessage,
)
from solution_architect_ai.application.prompts.clarification_prompt import SYSTEM_PROMPT
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.messages import MessageRole


class ClarificationContextBuilder:
    def build(
        self,
        documents: tuple[ParsedDocument, ...],
        requirements: list[RequirementView],
        history: list[ClarificationQuestion],
        decisions: list[DecisionResult],
        profile: ModelProfile,
    ) -> ClarificationContext:
        fragments: tuple[ContextFragment, ...] = tuple(
            ContextFragment(
                document.file_id,
                document.version_id,
                document.sha256,
                fragment.fragment_id,
                fragment.locator,
                fragment.text,
                0,
                len(fragment.text),
            )
            for document in documents
            for fragment in document.fragments
        )
        return self.build_fragments(fragments, requirements, history, decisions, profile)

    def build_fragments(
        self,
        fragments: tuple[ContextFragment, ...],
        requirements: list[RequirementView],
        history: list[ClarificationQuestion],
        decisions: list[DecisionResult],
        profile: ModelProfile,
    ) -> ClarificationContext:
        source_aliases: dict[str, str] = {
            f"f{index}": str(fragment.fragment_id) for index, fragment in enumerate(fragments)
        }
        requirement_aliases: dict[str, str] = {
            f"r{index}": str(requirement.id) for index, requirement in enumerate(requirements)
        }
        source_keys: dict[str, str] = {
            identifier: alias for alias, identifier in source_aliases.items()
        }
        requirement_keys: dict[str, str] = {
            identifier: alias for alias, identifier in requirement_aliases.items()
        }
        file_ids: set[UUID] = {fragment.file_id for fragment in fragments}
        history = [
            question
            for question in history
            if any(source.file_id in file_ids for source in question.sources)
        ]
        history_ids: set[UUID] = {question.id for question in history}
        decisions = [decision for decision in decisions if decision.question_id in history_ids]
        payload: ClarificationPayload = ClarificationPayload(
            fragments=[
                ContextSource(
                    fragment_id=source_keys[str(fragment.fragment_id)], text=fragment.text
                )
                for fragment in fragments
            ],
            requirements=[
                RequirementContext(
                    id=requirement_keys[str(requirement.id)],
                    category=requirement.category,
                    original_text=requirement.original_text,
                    normalized_text=requirement.normalized_text,
                    fragment_ids=[
                        source_keys[source.fragment_id]
                        for source in requirement.sources
                        if source.fragment_id in source_keys
                    ],
                    evidence=[
                        RequirementEvidenceContext(
                            fragment_id=source_keys[source.fragment_id],
                            candidate_quote=source.quote,
                            status=source.status,
                            reason=source.reason,
                        )
                        for source in requirement.sources
                        if source.fragment_id in source_keys
                    ],
                )
                for requirement in requirements
            ],
            history=[
                QuestionHistoryContext(
                    id=question.id,
                    gap_key=question.gap_key,
                    revision=question.revision,
                    text=question.text,
                    basis=question.basis,
                    status=question.status,
                    requirement_ids=question.requirement_ids,
                    sources=[
                        HistoricalSourceContext(
                            fragment_id=source.fragment_id,
                            version_id=source.version_id,
                            quote=source.quote,
                            status=source.status,
                            reason=source.reason,
                        )
                        for source in question.sources
                    ],
                )
                for question in history
            ],
            decisions=[DecisionHistoryContext.from_decision(decision) for decision in decisions],
            coverage=ContextCoverage(
                selected_versions=sorted({fragment.version_id for fragment in fragments}, key=str)
            ),
        )
        messages: tuple[StructuredMessage, ...] = (
            StructuredMessage(MessageRole.SYSTEM, SYSTEM_PROMPT),
            StructuredMessage(MessageRole.USER, payload.model_dump_json()),
        )
        return ClarificationContext(
            ContextPart("clarification", fragments, messages, 0),
            frozenset(str(requirement.id) for requirement in requirements),
            tuple(history),
            profile,
            MappingProxyType(source_aliases),
            MappingProxyType(requirement_aliases),
            tuple(requirements),
            payload,
            decisions=tuple(decisions),
        )

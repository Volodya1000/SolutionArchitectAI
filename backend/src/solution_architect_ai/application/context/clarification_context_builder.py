import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment, ContextPart
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


@dataclass(frozen=True)
class ClarificationContext:
    part: ContextPart
    requirement_ids: frozenset[str]
    history: tuple[ClarificationQuestion, ...]
    profile: ModelProfile
    source_aliases: Mapping[str, str]
    requirement_aliases: Mapping[str, str]
    requirements: tuple[RequirementView, ...]


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
        payload: dict[str, object] = {
            "role": "clarification",
            "fragments": [
                {"fragment_id": source_keys[str(fragment.fragment_id)], "text": fragment.text}
                for fragment in fragments
            ],
            "requirements": [
                {
                    "id": requirement_keys[str(requirement.id)],
                    "fragment_ids": [
                        source_keys[source.fragment_id]
                        for source in requirement.sources
                        if source.fragment_id in source_keys
                    ],
                }
                for requirement in requirements
            ],
            "history": [
                question.model_dump(
                    mode="json", exclude={"source_fingerprints", "requirement_fingerprints"}
                )
                for question in history
            ],
            "decisions": [decision.model_dump(mode="json") for decision in decisions],
            "coverage": {
                "selected_versions": sorted({str(fragment.version_id) for fragment in fragments}),
                "omitted_fragments": [],
            },
        }
        messages: tuple[StructuredMessage, ...] = (
            StructuredMessage(MessageRole.SYSTEM, SYSTEM_PROMPT),
            StructuredMessage(MessageRole.USER, json.dumps(payload, ensure_ascii=False)),
        )
        return ClarificationContext(
            ContextPart("clarification", fragments, messages, 0),
            frozenset(str(requirement.id) for requirement in requirements),
            tuple(history),
            replace(profile, output_limit=min(profile.output_limit, 2048)),
            MappingProxyType(source_aliases),
            MappingProxyType(requirement_aliases),
            tuple(requirements),
        )

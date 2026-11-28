import json
from dataclasses import asdict
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel

from solution_architect_ai.application.context.clarification_history_matcher import (
    ClarificationHistoryMatcher,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.clarification_step_models import (
    ClarificationStepResult,
)
from solution_architect_ai.application.models.extraction_models import SourceRef
from solution_architect_ai.application.models.structured_models import StructuredRequest
from solution_architect_ai.application.prompts.structured_prompt import render_messages
from solution_architect_ai.application.protocols.clarification_protocols import ClarificationStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.domain.requirements import EvidenceStatus


def validate_cached_questions(
    questions: list[ClarificationQuestion], context: ClarificationContext
) -> None:
    identifiers: set[UUID] = {item.id for item in context.requirements}
    matcher: ClarificationHistoryMatcher = ClarificationHistoryMatcher(
        context.all_fragments or context.part.fragments, context.requirements
    )
    question: ClarificationQuestion
    for question in questions:
        validate_cached_question(question, identifiers, matcher, context.history)


def validate_cached_question(
    question: ClarificationQuestion,
    identifiers: set[UUID],
    matcher: ClarificationHistoryMatcher,
    history: tuple[ClarificationQuestion, ...],
) -> None:
    if not set(question.requirement_ids) <= identifiers:
        raise StoredExtractionCorrupt("stored_extraction_corrupt")
    if not cached_status_matches(question, history):
        raise StoredExtractionCorrupt("stored_extraction_corrupt")
    if any(not cached_source_matches(source, matcher) for source in question.sources):
        raise StoredExtractionCorrupt("stored_extraction_corrupt")


def cached_status_matches(
    question: ClarificationQuestion, history: tuple[ClarificationQuestion, ...]
) -> bool:
    return question.status == "open" or any(
        (item.id, item.revision, item.status) == (question.id, question.revision, question.status)
        for item in history
    )


def cached_source_matches(source: SourceRef, matcher: ClarificationHistoryMatcher) -> bool:
    rebound: SourceRef | None = matcher.rebind_source(source, matcher.source_fingerprints)
    return (
        source.status == EvidenceStatus.VERIFIED
        and rebound is not None
        and (source.file_id, source.version_id, source.sha256, source.fragment_id)
        == (rebound.file_id, rebound.version_id, rebound.sha256, rebound.fragment_id)
    )


class ClarificationReviewCache:
    def __init__(self, run_id: UUID, store_context: StoreContext[ClarificationStore]) -> None:
        self.run_id: UUID = run_id
        self.store_context: StoreContext[ClarificationStore] = store_context

    @staticmethod
    def key(
        context: ClarificationContext,
        request: StructuredRequest,
        schema: type[BaseModel],
        subject: BaseModel | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "contract": "clarification-review-step-1",
            "messages": [
                asdict(item)
                for item in render_messages(request, schema, include_native_schema=True)
            ],
            "profile": asdict(request.profile),
            "sources": dict(context.source_aliases),
            "requirements": dict(context.requirement_aliases),
            "fragments": [
                asdict(item) for item in (context.all_fragments or context.part.fragments)
            ],
            "history": [item.model_dump(mode="json") for item in context.history],
            "requirement_state": [item.model_dump(mode="json") for item in context.requirements],
            "decisions": [item.model_dump(mode="json") for item in context.decisions],
            "subject": subject.model_dump(mode="json") if subject is not None else None,
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    async def load(self, key: str) -> ClarificationStepResult | None:
        store: ClarificationStore
        async with self.store_context.open() as store:
            return await store.get_review_step(self.run_id, key)

    async def save(self, key: str, result: ClarificationStepResult) -> ClarificationStepResult:
        store: ClarificationStore
        async with self.store_context.open() as store:
            await store.save_review_step(self.run_id, key, result)
            saved: ClarificationStepResult | None = await store.get_review_step(self.run_id, key)
            if saved is None:
                raise StoredExtractionCorrupt("stored_extraction_corrupt")
            return saved

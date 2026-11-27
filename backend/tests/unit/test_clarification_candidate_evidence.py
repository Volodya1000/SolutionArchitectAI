import json
from typing import Final
from uuid import uuid4

import pytest

from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.models.clarification_agent_models import (
    ClarificationSet,
    QuestionCandidate,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import ModelProfile, StructuredMode
from solution_architect_ai.application.validation.clarification_validation import (
    validate_clarifications,
)
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory
from solution_architect_ai.infrastructure.parsers.document_parser import DocumentParser

SOURCE_TEXT: Final[str] = "Retain audit entries for 30 days."
FALSE_QUOTE: Final[str] = "Retain audit entries for 90 days."


def candidate_context(
    quote: str, status: EvidenceStatus, reason: str | None
) -> tuple[ClarificationContext, RequirementView]:
    document: ParsedDocument = DocumentParser().parse(
        uuid4(), uuid4(), SOURCE_TEXT.encode(), "requirements.md", "text/markdown"
    )
    requirement: RequirementView = RequirementView(
        id=uuid4(),
        category=RequirementCategory.FUNCTIONAL,
        original_text=quote,
        normalized_text=quote,
        sources=[
            SourceRef(
                file_id=document.file_id,
                version_id=document.version_id,
                sha256=document.sha256,
                fragment_id=str(document.fragments[0].fragment_id),
                locator=None,
                quote=quote,
                status=status,
                reason=reason,
            )
        ],
    )
    context: ClarificationContext = ClarificationContextBuilder().build(
        (document,),
        [requirement],
        [],
        [],
        ModelProfile("model", StructuredMode.NATIVE_JSON_SCHEMA, 12288, 6912, 256),
    )
    return context, requirement


@pytest.mark.parametrize(
    ("quote", "status", "reason"),
    [
        (SOURCE_TEXT, EvidenceStatus.VERIFIED, None),
        (FALSE_QUOTE, EvidenceStatus.UNVERIFIED, "quote_not_in_context"),
    ],
)
def test_model_payload_distinguishes_candidate_quote_from_source_text(
    quote: str, status: EvidenceStatus, reason: str | None
) -> None:
    context: ClarificationContext
    requirement: RequirementView
    context, requirement = candidate_context(quote, status, reason)
    payload: object = json.loads(context.part.messages[-1].content)
    assert isinstance(payload, dict)
    requirements: object = payload["requirements"]
    assert isinstance(requirements, list)
    candidate: object = requirements[0]
    assert isinstance(candidate, dict)
    evidence: object = candidate["evidence"]
    assert isinstance(evidence, list)
    binding: object = evidence[0]
    assert isinstance(binding, dict)

    assert "candidate_quote" in binding
    assert binding["candidate_quote"] == quote
    assert binding["status"] == status.value
    assert binding["reason"] == reason
    assert "quote" not in binding
    assert context.part.fragments[0].text == SOURCE_TEXT
    assert requirement.sources[0].quote == quote


def test_relabeling_candidate_evidence_does_not_accept_false_source_quotes() -> None:
    context: ClarificationContext
    requirement: RequirementView
    context, requirement = candidate_context(
        FALSE_QUOTE, EvidenceStatus.UNVERIFIED, "quote_not_in_context"
    )
    candidate: QuestionCandidate = QuestionCandidate(
        gap_key="audit.retention",
        text="Which retention period applies?",
        basis="Candidate differs from source.",
        dependent_decision="Choose the deletion deadline.",
        blocking=True,
        requirement_ids=[str(requirement.id)],
        evidence=[Evidence(fragment_id="f0", quote=FALSE_QUOTE)],
    )

    with pytest.raises(ValueError, match="Unverified clarification evidence"):
        validate_clarifications(ClarificationSet(questions=[candidate]), context)

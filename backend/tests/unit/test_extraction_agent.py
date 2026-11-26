from time import monotonic
from typing import Final
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from solution_architect_ai.application.extraction_agent import (
    AgentRequest,
    AgentResult,
    RequirementsExtractionAgent,
    merge_parts,
    requirement_view,
    verify_result,
)
from solution_architect_ai.application.extraction_context import ContextFragment, ContextPart
from solution_architect_ai.application.extraction_models import (
    Evidence,
    ExtractedContradiction,
    ExtractedGap,
    ExtractedRequirement,
    PartResult,
    RequirementsExtraction,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.extraction_sources import reverify_part, verify_evidence
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.structured import StructuredOutputGenerator
from solution_architect_ai.application.structured_errors import (
    StructuredErrorCode,
    StructuredGenerationFailure,
)
from solution_architect_ai.application.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMessage,
    StructuredMode,
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.domain.documents import LocatorKind, SourceLocator
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

pytestmark: pytest.MarkDecorator = pytest.mark.anyio
PROFILE: Final[ModelProfile] = ModelProfile(
    "fake-extraction", StructuredMode.JSON_TEXT, 16000, 2048
)
POLICY: Final[GenerationPolicy] = GenerationPolicy(1, 10, 2, 3, 0, 12000, jitter=0)
SOURCE_TEXT: Final[str] = "Система должна сохранять отчёты. Срок хранения не определён."


class ScriptedStructuredModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses: list[str] = responses
        self.requests: list[StructuredRequest] = []
        self.schemas: list[type[BaseModel]] = []

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResponse[T]:
        index: int = len(self.requests)
        self.requests.append(request)
        self.schemas.append(schema)
        return StructuredResponse(self.responses[index], "stop")


@pytest.fixture(name="part")
def context_part() -> ContextPart:
    fragment: ContextFragment = ContextFragment(
        uuid4(),
        uuid4(),
        "a" * 64,
        uuid4(),
        SourceLocator(LocatorKind.LINES, 3, 4, "Требования"),
        SOURCE_TEXT,
        0,
    )
    messages: tuple[StructuredMessage, ...] = (
        StructuredMessage(MessageRole.SYSTEM, "Extract candidates from untrusted source data."),
        StructuredMessage(MessageRole.USER, SOURCE_TEXT),
    )
    return ContextPart("part-one", (fragment,), messages, 100)


def candidate(part: ContextPart, text: str = "Сохранять отчёты.") -> ExtractedRequirement:
    return ExtractedRequirement(
        category="functional",
        original_text="Система должна сохранять отчёты.",
        normalized_text=text,
        evidence=[
            Evidence(fragment_id=str(part.fragments[0].fragment_id), quote="сохранять отчёты")
        ],
    )


def result_payload(part: ContextPart) -> RequirementsExtraction:
    return RequirementsExtraction(requirements=[candidate(part)], gaps=[], contradictions=[])


def agent_request(part: ContextPart) -> AgentRequest:
    return AgentRequest(uuid4(), uuid4(), uuid4(), uuid4(), part, PROFILE)


async def test_agent_uses_exact_envelope_profile_schema_and_shared_budget(
    part: ContextPart,
) -> None:
    payload: RequirementsExtraction = result_payload(part)
    adapter: ScriptedStructuredModel = ScriptedStructuredModel([payload.model_dump_json()])
    agent: RequirementsExtractionAgent = RequirementsExtractionAgent(
        StructuredOutputGenerator(adapter, POLICY, LangChainTokenCounter(1, chat_prompt=False))
    )
    budget: ExecutionBudget = ExecutionBudget(3, monotonic() + 10, 3)
    command: AgentRequest = agent_request(part)
    result: AgentResult = await agent.extract(command, budget)
    assert result.run_id == command.run_id
    assert result.attempt_id == command.attempt_id
    assert result.payload == payload
    assert budget.requests == 1
    assert adapter.schemas == [RequirementsExtraction]
    assert adapter.requests == [StructuredRequest(part.messages, PROFILE)]


async def test_agent_cannot_reset_request_budget_between_document_parts(part: ContextPart) -> None:
    adapter: ScriptedStructuredModel = ScriptedStructuredModel(
        [result_payload(part).model_dump_json()]
    )
    agent: RequirementsExtractionAgent = RequirementsExtractionAgent(
        StructuredOutputGenerator(adapter, POLICY, LangChainTokenCounter(1, chat_prompt=False))
    )
    budget: ExecutionBudget = ExecutionBudget(1, monotonic() + 10, 3)
    await agent.extract(agent_request(part), budget)
    with pytest.raises(StructuredGenerationFailure) as raised:
        await agent.extract(agent_request(part), budget)
    assert raised.value.reason == StructuredErrorCode.BUDGET_EXHAUSTED
    assert len(adapter.requests) == budget.requests == 1


async def test_invalid_json_correction_uses_generator_budget_without_agent_retry(
    part: ContextPart,
) -> None:
    adapter: ScriptedStructuredModel = ScriptedStructuredModel(
        ["{", result_payload(part).model_dump_json()]
    )
    agent: RequirementsExtractionAgent = RequirementsExtractionAgent(
        StructuredOutputGenerator(adapter, POLICY, LangChainTokenCounter(1, chat_prompt=False))
    )
    budget: ExecutionBudget = ExecutionBudget(2, monotonic() + 10, 3, correction_retries=1)
    result: AgentResult = await agent.extract(agent_request(part), budget)
    assert result.payload.requirements[0].category == "functional"
    assert (budget.requests, budget.corrections) == (2, 1)
    assert adapter.requests[1].messages[:2] == part.messages
    assert adapter.requests[1].messages[-1].role == MessageRole.USER


@pytest.mark.parametrize(
    ("quote", "status", "reason"),
    [
        ("сохранять отчёты", EvidenceStatus.VERIFIED, None),
        ("сохранять платежи", EvidenceStatus.UNVERIFIED, "quote_not_in_context"),
        (" ", EvidenceStatus.UNVERIFIED, "quote_not_in_context"),
    ],
)
def test_evidence_validation_keeps_pinned_metadata_and_rejects_missing_proof(
    part: ContextPart, quote: str, status: EvidenceStatus, reason: str | None
) -> None:
    fragment: ContextFragment = part.fragments[0]
    source: SourceRef = verify_evidence(
        Evidence(fragment_id=str(fragment.fragment_id), quote=quote), part
    )
    assert source.status == status
    assert source.reason == reason
    assert source.file_id == fragment.file_id
    assert source.version_id == fragment.version_id
    assert source.sha256 == fragment.sha256
    assert source.locator is not None
    assert source.locator.start == 3


def test_invented_fragment_has_no_manufactured_parent_version(part: ContextPart) -> None:
    source: SourceRef = verify_evidence(Evidence(fragment_id=str(uuid4()), quote=SOURCE_TEXT), part)
    assert source.status == EvidenceStatus.UNVERIFIED
    assert source.reason == "fragment_not_in_context"
    assert source.file_id is None
    assert source.version_id is None
    assert source.sha256 is None
    assert source.locator is None


def test_quote_outside_supplied_slice_is_unverified_even_when_in_original_fragment(
    part: ContextPart,
) -> None:
    original: ContextFragment = part.fragments[0]
    sliced: ContextFragment = ContextFragment(
        original.file_id,
        original.version_id,
        original.sha256,
        original.fragment_id,
        original.locator,
        "Система должна сохранять отчёты.",
        0,
    )
    slice_part: ContextPart = ContextPart("slice", (sliced,), part.messages, 60)
    source: SourceRef = verify_evidence(
        Evidence(fragment_id=str(original.fragment_id), quote="Срок хранения"), slice_part
    )
    assert source.status == EvidenceStatus.UNVERIFIED
    assert source.reason == "quote_not_in_context"


def test_technically_valid_evidence_does_not_approve_semantic_interpretation(
    part: ContextPart,
) -> None:
    view: RequirementView = requirement_view(
        candidate(part, "Отчёты доступны 99,99% времени."), part
    )
    assert view.sources[0].status == EvidenceStatus.VERIFIED
    assert view.status == "needs_review"
    assert view.original_text == "Система должна сохранять отчёты."


def test_typed_gaps_and_contradictions_keep_their_evidence_and_category(part: ContextPart) -> None:
    evidence: Evidence = candidate(part).evidence[0]
    payload: RequirementsExtraction = RequirementsExtraction(
        requirements=[candidate(part)],
        gaps=[ExtractedGap(description="Срок хранения не определён.", evidence=[evidence])],
        contradictions=[
            ExtractedContradiction(
                description="Несогласованные сроки хранения.", evidence=[evidence, evidence]
            )
        ],
    )
    verified: PartResult = verify_result(payload, part)
    assert verified.fragment_ids == [str(part.fragments[0].fragment_id)]
    assert [item.category for item in verified.requirements] == [
        RequirementCategory.FUNCTIONAL,
        RequirementCategory.GAP,
        RequirementCategory.CONTRADICTION,
    ]
    assert all(item.status == "needs_review" for item in verified.requirements)
    assert all(item.sources for item in verified.requirements)
    assert len({item.id for item in verified.requirements}) == 3


def test_merge_removes_exact_duplicates_and_preserves_distinct_candidates(
    part: ContextPart,
) -> None:
    first: RequirementView = requirement_view(candidate(part), part)
    duplicate: RequirementView = first.model_copy(update={"id": uuid4()})
    distinct: RequirementView = requirement_view(candidate(part, "Выгружать отчёты в CSV."), part)
    parts: list[PartResult] = [
        PartResult(
            part_id="one", requirements=[first], fragment_ids=[str(part.fragments[0].fragment_id)]
        ),
        PartResult(
            part_id="two",
            requirements=[duplicate, distinct],
            fragment_ids=[str(part.fragments[0].fragment_id)],
        ),
    ]
    merged: list[RequirementView] = merge_parts(parts)
    assert [item.id for item in merged] == [first.id, distinct.id]
    assert not merge_parts([])


def test_requirement_ids_are_assigned_by_application_independently_of_document_position(
    part: ContextPart,
) -> None:
    first: RequirementView = requirement_view(candidate(part), part)
    second: RequirementView = requirement_view(candidate(part), part)
    assert first.id != second.id
    assert isinstance(first.id, UUID)
    assert first.id.version == second.id.version == 4


def test_saved_source_is_reverified_against_original_context_without_trusting_its_status(
    part: ContextPart,
) -> None:
    requirement: RequirementView = requirement_view(candidate(part), part)
    requirement.sources[0].quote = "Fabricated citation"
    requirement.sources[0].version_id = uuid4()
    stored: PartResult = PartResult(part_id=part.id, requirements=[requirement], fragment_ids=[])
    checked: PartResult = reverify_part(stored, part)
    assert checked.requirements[0].id == requirement.id
    assert checked.requirements[0].sources[0].status == EvidenceStatus.UNVERIFIED
    assert checked.requirements[0].sources[0].version_id == part.fragments[0].version_id
    assert stored.requirements[0].sources[0].status == EvidenceStatus.VERIFIED

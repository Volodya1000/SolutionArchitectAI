import json
from dataclasses import asdict, dataclass
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.protocols.chat_protocols import TokenCounter
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import RequirementCategory


@dataclass(frozen=True)
class SampleEvidence:
    fragment_id: str
    quote: str


@dataclass(frozen=True)
class SampleRequirement:
    category: RequirementCategory
    original_text: str
    normalized_text: str
    evidence: list[SampleEvidence]


@dataclass(frozen=True)
class SampleResponse:
    requirements: list[SampleRequirement]
    gaps: tuple[()] = ()
    contradictions: tuple[()] = ()


def estimate_response_tokens(fragments: tuple[ContextFragment, ...], tokens: TokenCounter) -> int:
    # A sizing sample can exceed extraction field limits; it is not a model response.
    payload: SampleResponse = SampleResponse(
        [
            SampleRequirement(
                RequirementCategory.SYSTEM_BOUNDARY,
                item.text,
                item.text,
                [SampleEvidence(str(item.fragment_id), item.text)],
            )
            for item in fragments
        ]
    )
    sample: MessageView = MessageView(
        id=UUID(int=0),
        role=MessageRole.ASSISTANT,
        content=json.dumps(asdict(payload), ensure_ascii=False, separators=(",", ":")),
        position=0,
        incomplete=False,
    )
    return tokens.count([sample])

import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from solution_architect_ai.application.context.context_models import (
    ContextFragment,
    ContextPart,
    ContextPolicy,
)
from solution_architect_ai.application.models.structured_models import StructuredMessage
from solution_architect_ai.application.prompts.extraction_prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)
from solution_architect_ai.application.prompts.structured_prompt import CORRECTION_PROMPT
from solution_architect_ai.domain.documents import ParsedDocument


@dataclass(frozen=True)
class ContextIdentity:
    prompt: str
    prompt_hash: str
    rendered_prompt_hash: str
    builder_version: str
    parsers: list[tuple[str, str]]
    schema: str
    correction_hash: str
    scope: str
    parts: list[str]
    policy: tuple[int, int, int, str, int]


def part_digest(fragments: tuple[ContextFragment, ...]) -> str:
    identity: str = "|".join(
        f"{item.version_id}:{item.sha256}:{item.fragment_id}:{item.offset}:{item.locator}:{item.text}"
        for item in fragments
    )
    return sha256(identity.encode()).hexdigest()


def context_digest(
    documents: tuple[ParsedDocument, ...],
    parts: tuple[ContextPart, ...],
    scope: str,
    schema: str,
    policy: ContextPolicy,
    rendered: tuple[StructuredMessage, ...],
) -> str:
    identity: ContextIdentity = ContextIdentity(
        PROMPT_VERSION,
        sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        sha256(
            json.dumps(
                [(item.role.value, item.content) for item in rendered], ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "context-6",
        [(str(doc.version_id), doc.parser_version) for doc in documents],
        schema,
        sha256(CORRECTION_PROMPT.encode()).hexdigest(),
        scope,
        [part.id for part in parts],
        (
            policy.context_window,
            policy.output_limit,
            policy.service_tokens,
            policy.mode.value,
            policy.correction_retries,
        ),
    )
    return sha256(json.dumps(asdict(identity), sort_keys=True).encode()).hexdigest()

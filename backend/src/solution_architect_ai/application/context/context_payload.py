from dataclasses import dataclass


@dataclass(frozen=True)
class PromptFragment:
    fragment_id: str
    text: str
    section: str
    path: str


@dataclass(frozen=True)
class ContextPayload:
    analysis_scope: str
    fragments: list[PromptFragment]

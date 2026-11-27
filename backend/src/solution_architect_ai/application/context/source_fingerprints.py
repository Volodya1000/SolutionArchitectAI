import json
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import RequirementView


def requirement_fingerprint(requirement: RequirementView) -> str:
    payload: tuple[str, str, list[tuple[str, str]]] = (
        requirement.category.value,
        requirement.original_text,
        sorted((str(source.file_id), source.quote) for source in requirement.sources),
    )
    return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def requirement_basis_fingerprint(requirement: RequirementView) -> str:
    return sha256(
        json.dumps(
            (requirement.category.value, " ".join(requirement.original_text.split())),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def has_changed_clarification_basis(
    previous: ClarificationQuestion, current: ClarificationQuestion
) -> bool:
    if (
        previous.requirement_basis_fingerprints
        and current.requirement_basis_fingerprints
        and set(previous.requirement_basis_fingerprints.values())
        != set(current.requirement_basis_fingerprints.values())
    ):
        return True
    if (
        not (previous.requirement_basis_fingerprints and current.requirement_basis_fingerprints)
        and previous.requirement_fingerprints
        and current.requirement_fingerprints
        and set(previous.requirement_fingerprints.values())
        != set(current.requirement_fingerprints.values())
    ):
        return True
    return has_changed_source_basis(previous, current)


def fingerprint_fragment_content(
    file_id: UUID, chunks: list[tuple[int, str]], lengths: set[int]
) -> str:
    expected_offset: int = 0
    content: list[str] = []
    complete: bool = True
    offset: int
    text: str
    for offset, text in sorted(set(chunks)):
        if offset != expected_offset:
            complete = False
        content.append(text)
        expected_offset = offset + len(text)
    complete = complete and all(length in {0, expected_offset} for length in lengths)
    # Incomplete coverage never matches the fingerprint of a complete source.
    payload: tuple[str, str, bool] = (str(file_id), "".join(content), complete)
    return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def fragment_fingerprints(fragments: tuple[ContextFragment, ...]) -> dict[str, str]:
    pieces: dict[UUID, list[tuple[int, str]]] = {}
    scopes: dict[UUID, UUID] = {}
    lengths: dict[UUID, set[int]] = {}
    fragment: ContextFragment
    for fragment in fragments:
        pieces.setdefault(fragment.fragment_id, []).append((fragment.offset, fragment.text))
        scopes[fragment.fragment_id] = fragment.file_id
        lengths.setdefault(fragment.fragment_id, set()).add(fragment.total_length)
    return {
        str(identifier): fingerprint_fragment_content(
            scopes[identifier], chunks, lengths[identifier]
        )
        for identifier, chunks in pieces.items()
    }


def has_changed_source_basis(
    previous: ClarificationQuestion, current: ClarificationQuestion
) -> bool:
    if previous.source_fingerprints and current.source_fingerprints:
        return set(previous.source_fingerprints.values()) != set(
            current.source_fingerprints.values()
        )
    return {(source.file_id, source.quote) for source in previous.sources} != {
        (source.file_id, source.quote) for source in current.sources
    }

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from solution_architect_ai.domain.errors import StartConflict


@dataclass(frozen=True)
class StartCandidate:
    run_id: UUID
    command_id: UUID
    payload_digest: str


def content_digest(content: str) -> str:
    return sha256(content.encode()).hexdigest()


def replay_run(command_id: UUID, digest: str, candidates: Sequence[StartCandidate]) -> UUID | None:
    """Candidates include the matching command and any active run on the locked chat."""
    candidate: StartCandidate
    for candidate in candidates:
        if candidate.command_id == command_id:
            if candidate.payload_digest != digest:
                raise StartConflict("command_payload_conflict")
            return candidate.run_id
    if candidates:
        raise StartConflict("chat_has_active_run")
    return None


def message_positions(last: int | None) -> tuple[int, int]:
    user: int = (last or 0) + 1
    return user, user + 1

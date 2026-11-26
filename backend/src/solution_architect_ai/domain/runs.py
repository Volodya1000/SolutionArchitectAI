from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.COMPLETED, RunStatus.CANCELLING, RunStatus.FAILED},
    RunStatus.CANCELLING: {RunStatus.CANCELLED, RunStatus.FAILED},
}


def transition(current: RunStatus, target: RunStatus) -> RunStatus:
    if target not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid run transition: {current} -> {target}")
    return target


def resolve_transition(
    current: RunStatus, target: RunStatus, error: str | None = None
) -> RunStatus:
    """Resolve replayed commands and worker/cancellation races before validation."""
    if error is not None and target not in {RunStatus.FAILED, RunStatus.CANCELLED}:
        raise ValueError("Only failed or cancelled runs can carry an error")
    if current.terminal or current == target:
        return current
    if target == RunStatus.RUNNING and current != RunStatus.QUEUED:
        return current
    if current == RunStatus.CANCELLING and target == RunStatus.COMPLETED:
        return current
    return transition(current, target)

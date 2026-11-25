import pytest

from solution_architect_ai.domain.runs import RunStatus, transition


@pytest.mark.parametrize("status", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_terminal_status_cannot_be_changed(status: RunStatus) -> None:
    with pytest.raises(ValueError, match=r".+"):
        transition(status, RunStatus.RUNNING)


def test_cancellation_must_be_confirmed_before_terminal_state() -> None:
    assert transition(RunStatus.RUNNING, RunStatus.CANCELLING) == RunStatus.CANCELLING
    assert transition(RunStatus.CANCELLING, RunStatus.CANCELLED) == RunStatus.CANCELLED
    with pytest.raises(ValueError, match=r".+"):
        transition(RunStatus.CANCELLING, RunStatus.COMPLETED)


def test_queued_run_cannot_complete_without_starting() -> None:
    with pytest.raises(ValueError, match=r".+"):
        transition(RunStatus.QUEUED, RunStatus.COMPLETED)

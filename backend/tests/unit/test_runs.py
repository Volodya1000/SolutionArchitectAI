import pytest

from solution_architect_ai.domain import runs
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus, transition


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


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        (RunStatus.CANCELLED, RunStatus.RUNNING, RunStatus.CANCELLED),
        (RunStatus.COMPLETED, RunStatus.CANCELLING, RunStatus.COMPLETED),
        (RunStatus.FAILED, RunStatus.COMPLETED, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.RUNNING, RunStatus.RUNNING),
        (RunStatus.CANCELLING, RunStatus.RUNNING, RunStatus.CANCELLING),
        (RunStatus.CANCELLING, RunStatus.COMPLETED, RunStatus.CANCELLING),
        (RunStatus.CANCELLING, RunStatus.CANCELLED, RunStatus.CANCELLED),
    ],
)
def test_racing_status_commands_obey_domain_precedence(
    current: RunStatus, target: RunStatus, expected: RunStatus
) -> None:
    assert runs.resolve_transition(current, target) == expected


def test_successful_transition_cannot_carry_an_error() -> None:
    with pytest.raises(ValueError, match="error"):
        runs.resolve_transition(
            RunStatus.RUNNING, RunStatus.COMPLETED, RunErrorCode.LLM_UNAVAILABLE
        )

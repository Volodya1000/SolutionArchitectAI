from uuid import UUID, uuid4

import pytest
from langgraph.types import StateSnapshot

from solution_architect_ai.infrastructure.extraction_graph import LangGraphExtraction


def checkpoint(values: object) -> object:
    return StateSnapshot(
        values=values,
        next=("prepare",),
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=(),
        interrupts=(),
    )


def test_pr2_checkpoint_without_cycle_uses_initial_cycle() -> None:
    run_id: UUID = uuid4()
    assert (
        LangGraphExtraction.checkpoint_cycle(
            checkpoint({"run_id": str(run_id), "index": 0}), run_id, 0
        )
        == 0
    )


@pytest.mark.parametrize("cycle", [None, True, False, -1, "0", 1.5, 1])
def test_invalid_or_future_checkpoint_cycle_is_rejected(cycle: object) -> None:
    run_id: UUID = uuid4()
    with pytest.raises(TypeError, match="Invalid checkpoint clarification cycle"):
        LangGraphExtraction.checkpoint_cycle(
            checkpoint({"run_id": str(run_id), "cycle": cycle}), run_id, 0
        )


def test_checkpoint_from_another_run_is_rejected() -> None:
    with pytest.raises(TypeError, match="Invalid checkpoint run"):
        LangGraphExtraction.checkpoint_cycle(
            checkpoint({"run_id": str(uuid4()), "cycle": 0}), uuid4(), 0
        )

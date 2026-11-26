from uuid import uuid4

import pytest

from solution_architect_ai.application.context import select_context
from solution_architect_ai.application.dto import MessageView, Role
from solution_architect_ai.application.errors import GenerationFailure


def message(role: Role, content: str, *, incomplete: bool = False) -> MessageView:
    return MessageView(id=uuid4(), position=1, role=role, content=content, incomplete=incomplete)


def test_history_eviction_keeps_whole_turns() -> None:
    history: list[MessageView] = [
        message("user", "x" * 2100),
        message("assistant", "old answer"),
        message("user", "retained"),
        message("assistant", "retained answer"),
        message("user", "latest"),
        message("assistant", "", incomplete=True),
    ]
    assert select_context(history, 2000) == history[2:-1]


def test_incomplete_output_excludes_its_question_from_history() -> None:
    history: list[MessageView] = [
        message("user", "failed question"),
        message("assistant", "partial", incomplete=True),
        message("user", "latest"),
        message("assistant", "", incomplete=True),
    ]
    assert select_context(history, 2000) == [history[-2]]


def test_newest_prompt_includes_system_and_template_cost() -> None:
    with pytest.raises(GenerationFailure, match="context_too_large"):
        select_context([message("user", "я" * 200)], 500)

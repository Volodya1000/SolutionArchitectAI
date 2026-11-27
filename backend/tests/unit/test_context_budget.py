from typing import Final
from uuid import uuid4

import pytest

from solution_architect_ai.application.context.chat_context_builder import select_context
from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.infrastructure.context import LangChainTokenCounter

COUNTER: Final[LangChainTokenCounter] = LangChainTokenCounter(1)


def message(role: MessageRole, content: str, *, incomplete: bool = False) -> MessageView:
    return MessageView(id=uuid4(), position=1, role=role, content=content, incomplete=incomplete)


def test_history_eviction_keeps_whole_turns() -> None:
    history: list[MessageView] = [
        message(MessageRole.USER, "x" * 2100),
        message(MessageRole.ASSISTANT, "old answer"),
        message(MessageRole.USER, "retained"),
        message(MessageRole.ASSISTANT, "retained answer"),
        message(MessageRole.USER, "latest"),
        message(MessageRole.ASSISTANT, "", incomplete=True),
    ]
    assert select_context(history, 2000, COUNTER) == history[2:-1]


def test_incomplete_output_excludes_its_question_from_history() -> None:
    history: list[MessageView] = [
        message(MessageRole.USER, "failed question"),
        message(MessageRole.ASSISTANT, "partial", incomplete=True),
        message(MessageRole.USER, "latest"),
        message(MessageRole.ASSISTANT, "", incomplete=True),
    ]
    assert select_context(history, 2000, COUNTER) == [history[-2]]


def test_newest_prompt_includes_system_and_template_cost() -> None:
    with pytest.raises(GenerationFailure, match="context_too_large"):
        select_context([message(MessageRole.USER, "я" * 200)], 300, COUNTER)


def test_library_estimate_keeps_a_cyrillic_request_that_fits() -> None:
    question: MessageView = message(MessageRole.USER, "я" * 200)
    assert select_context([question], 500, COUNTER) == [question]


class RecordingCounter:
    def __init__(self) -> None:
        self.calls: int = 0

    def count(self, messages: list[MessageView]) -> int:
        self.calls += 1
        return len(messages)


def test_long_history_does_not_recount_every_growing_turn() -> None:
    history: list[MessageView] = []
    _index: int
    for _index in range(800):
        history.extend((message(MessageRole.USER, "q"), message(MessageRole.ASSISTANT, "a")))
    history.append(message(MessageRole.USER, "latest"))
    tokens: RecordingCounter = RecordingCounter()
    assert select_context(history, len(history), tokens) == history
    assert tokens.calls <= 20

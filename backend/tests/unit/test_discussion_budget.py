from uuid import uuid4

import pytest

from solution_architect_ai.application.context.chat_context_builder import select_context
from solution_architect_ai.application.context.discussion_context_builder import context_message
from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.runs import RunErrorCode
from solution_architect_ai.infrastructure.context import LangChainTokenCounter


def test_discussion_source_and_complete_turns_share_one_budget() -> None:
    tokens: LangChainTokenCounter = LangChainTokenCounter(2)
    prefix: list[MessageView] = [
        context_message(MessageRole.SYSTEM, "Use only pinned evidence"),
        context_message(MessageRole.USER, "Source evidence " * 100),
    ]
    question: MessageView = MessageView(
        id=uuid4(), role=MessageRole.USER, content="Explain R03", position=2, incomplete=False
    )
    messages: list[MessageView] = [
        context_message(MessageRole.USER, "Old question " * 100),
        context_message(MessageRole.ASSISTANT, "Old answer " * 100),
        question,
    ]
    budget: int = tokens.count([*prefix, question])
    selected: list[MessageView] = select_context(messages, budget, tokens, prefix)
    assert selected == [*prefix, question]
    assert tokens.count(selected) <= budget
    failure: pytest.ExceptionInfo[GenerationFailure]
    with pytest.raises(GenerationFailure) as failure:
        select_context(messages, budget - 1, tokens, prefix)
    assert failure.value.code == RunErrorCode.CONTEXT_TOO_LARGE

from typing import Final

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.errors import GenerationFailure
from solution_architect_ai.domain.runs import RunErrorCode

SYSTEM_PROMPT: Final[str] = (
    "Ты помощник solution-архитектора. Отвечай по-русски, ясно и по существу. "
    "Не выдавай предположения за факты. Ответ не означает согласования архитектуры."
)
# Byte-based upper estimate for content, plus allowances for the chat template:
# role tags/delimiters on every message and the final assistant generation prefix.
MESSAGE_OVERHEAD: Final[int] = 32
GENERATION_OVERHEAD: Final[int] = 64
FIXED_INPUT_COST: Final[int] = len(SYSTEM_PROMPT.encode()) + MESSAGE_OVERHEAD + GENERATION_OVERHEAD


def message_cost(message: MessageView) -> int:
    return len(message.content.encode()) + MESSAGE_OVERHEAD


def pending_question_index(messages: list[MessageView]) -> int:
    latest: int = len(messages) - 1
    if latest >= 0 and messages[latest].role == "assistant" and messages[latest].incomplete:
        latest -= 1
    if latest < 0 or messages[latest].role != "user":
        raise GenerationFailure(RunErrorCode.CONTEXT_TOO_LARGE)
    return latest


def complete_turn(question: MessageView, answer: MessageView) -> bool:
    return question.role == "user" and answer.role == "assistant" and not answer.incomplete


def select_context(messages: list[MessageView], input_budget: int) -> list[MessageView]:
    """Keep a suffix of complete turns and the pending question, within the input reserve."""
    latest: int = pending_question_index(messages)
    question: MessageView = messages[latest]
    remaining: int = input_budget - FIXED_INPUT_COST - message_cost(question)
    if remaining < 0:
        raise GenerationFailure(RunErrorCode.CONTEXT_TOO_LARGE)
    reverse_order: list[MessageView] = [question]
    index: int
    for index in range(latest - 1, 0, -2):
        answer: MessageView = messages[index]
        previous: MessageView = messages[index - 1]
        if not complete_turn(previous, answer):
            continue
        remaining -= message_cost(previous) + message_cost(answer)
        if remaining < 0:
            break
        reverse_order.extend((answer, previous))
    reverse_order.reverse()
    return reverse_order

from bisect import bisect_right

from solution_architect_ai.application.errors.chat_errors import GenerationFailure
from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.application.protocols.chat_protocols import TokenCounter
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.runs import RunErrorCode


def pending_question_index(messages: list[MessageView]) -> int:
    latest: int = len(messages) - 1
    if (
        latest >= 0
        and messages[latest].role == MessageRole.ASSISTANT
        and messages[latest].incomplete
    ):
        latest -= 1
    if latest < 0 or messages[latest].role != MessageRole.USER:
        raise GenerationFailure(RunErrorCode.CONTEXT_TOO_LARGE)
    return latest


def complete_turn(question: MessageView, answer: MessageView) -> bool:
    return (
        question.role == MessageRole.USER
        and answer.role == MessageRole.ASSISTANT
        and not answer.incomplete
    )


def assemble_context(
    turns: list[tuple[MessageView, MessageView]], count: int, question: MessageView
) -> list[MessageView]:
    return [item for turn in reversed(turns[:count]) for item in turn] + [question]


def select_context(
    messages: list[MessageView],
    input_budget: int,
    tokens: TokenCounter,
    prefix: list[MessageView] | None = None,
) -> list[MessageView]:
    required: list[MessageView] = [] if prefix is None else prefix
    latest: int = pending_question_index(messages)
    question: MessageView = messages[latest]
    if tokens.count([*required, question]) > input_budget:
        raise GenerationFailure(RunErrorCode.CONTEXT_TOO_LARGE)
    turns: list[tuple[MessageView, MessageView]] = []
    index: int
    for index in range(latest - 1, 0, -2):
        answer: MessageView = messages[index]
        previous: MessageView = messages[index - 1]
        if not complete_turn(previous, answer):
            continue
        turns.append((previous, answer))

    def estimated_size(count: int) -> int:
        return tokens.count([*required, *assemble_context(turns, count, question)])

    count: int = bisect_right(range(len(turns) + 1), input_budget, key=estimated_size) - 1
    return [*required, *assemble_context(turns, count, question)]

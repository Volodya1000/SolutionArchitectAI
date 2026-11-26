from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.application.prompts import SYSTEM_PROMPT
from solution_architect_ai.domain.messages import MessageRole


def build_messages(messages: list[MessageView]) -> list[BaseMessage]:
    inputs: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    inputs.extend(
        HumanMessage(content=item.content)
        if item.role == MessageRole.USER
        else AIMessage(content=item.content)
        for item in messages
    )
    return inputs

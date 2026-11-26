from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.utils import count_tokens_approximately

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.infrastructure.prompts import build_messages


class LangChainTokenCounter:
    def __init__(self, chars_per_token: float) -> None:
        self.chars_per_token: float = chars_per_token

    def count(self, messages: list[MessageView]) -> int:
        inputs: list[BaseMessage] = [*build_messages(messages), AIMessage(content="")]
        return count_tokens_approximately(inputs, chars_per_token=self.chars_per_token)

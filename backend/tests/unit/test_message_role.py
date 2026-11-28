from uuid import uuid4

import pytest

from solution_architect_ai.application.models.chat_dto import MessageView
from solution_architect_ai.domain.messages import MessageRole


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (MessageRole.SYSTEM, "system"),
        (MessageRole.USER, "user"),
        (MessageRole.ASSISTANT, "assistant"),
    ],
)
def test_message_roles_preserve_the_api_strings(role: MessageRole, expected: str) -> None:
    message: MessageView = MessageView(
        id=uuid4(), role=role, content="text", position=1, incomplete=False
    )
    assert isinstance(message.role, MessageRole)
    assert str(message.role) == expected
    assert message.model_dump(mode="json")["role"] == expected

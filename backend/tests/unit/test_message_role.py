from uuid import uuid4

import pytest

from solution_architect_ai.application.dto import MessageView
from solution_architect_ai.domain.messages import MessageRole


@pytest.mark.parametrize("role", list(MessageRole))
def test_message_roles_preserve_the_api_strings(role: MessageRole) -> None:
    message: MessageView = MessageView(
        id=uuid4(), role=role, content="text", position=1, incomplete=False
    )
    assert isinstance(message.role, MessageRole)
    assert str(message.role) == role.value
    assert message.model_dump(mode="json")["role"] == role.value

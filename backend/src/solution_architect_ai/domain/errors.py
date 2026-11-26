from typing import Literal


class StartConflict(ValueError):
    def __init__(self, reason: Literal["command_payload_conflict", "chat_has_active_run"]) -> None:
        super().__init__(reason)
        self.reason: Literal["command_payload_conflict", "chat_has_active_run"] = reason

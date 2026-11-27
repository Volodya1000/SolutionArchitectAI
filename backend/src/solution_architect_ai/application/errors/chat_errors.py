from solution_architect_ai.domain.runs import RunErrorCode


class ChatError(Exception):
    pass


class Missing(ChatError):
    pass


class Conflict(ChatError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code: str = code


class StorageUnavailable(ChatError):
    pass


class GenerationFailure(Exception):
    def __init__(
        self, code: RunErrorCode, *, retryable: bool = False, retry_after: float = 0
    ) -> None:
        super().__init__(code)
        self.code: RunErrorCode = code
        self.retryable: bool = retryable
        self.retry_after: float = retry_after

class ExtractionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code: str = code


class ContextTooLarge(ExtractionError):
    def __init__(self, detail: str) -> None:
        super().__init__("context_too_large")
        self.detail: str = detail


class ExtractionInterrupted(ExtractionError):
    pass


class StoredExtractionCorrupt(ExtractionError):
    pass

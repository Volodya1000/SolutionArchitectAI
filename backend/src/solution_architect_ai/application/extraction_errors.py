class ExtractionError(Exception):
    pass


class ContextTooLarge(ExtractionError):
    pass


class ExtractionInterrupted(ExtractionError):
    pass

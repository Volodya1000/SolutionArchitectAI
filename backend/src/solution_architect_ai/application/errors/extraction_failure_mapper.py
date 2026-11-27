from solution_architect_ai.application.errors.chat_errors import Conflict
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.errors.extraction_errors import ExtractionError
from solution_architect_ai.application.errors.structured_errors import StructuredGenerationFailure
from solution_architect_ai.domain.runs import RunErrorCode


def extraction_failure_code(
    error: StructuredGenerationFailure
    | ExtractionError
    | TimeoutError
    | DocumentFailure
    | Conflict,
) -> str:
    if isinstance(error, StructuredGenerationFailure):
        return error.reason.value
    if isinstance(error, TimeoutError):
        return RunErrorCode.DEADLINE_EXCEEDED.value
    return error.code

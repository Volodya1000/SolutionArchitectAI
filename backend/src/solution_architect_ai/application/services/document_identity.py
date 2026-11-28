import json
from hashlib import sha256
from typing import Final

from pydantic import TypeAdapter

from solution_architect_ai.application.models.document_dto import UploadDocument
from solution_architect_ai.application.protocols.document_protocols import StagedFile
from solution_architect_ai.domain.documents import ParsedDocument

PARSED_DOCUMENT: Final[TypeAdapter[ParsedDocument]] = TypeAdapter(ParsedDocument)


def parse_digest(document: ParsedDocument) -> str:
    # Derived syntax metadata must not change historical saved-parse hashes.
    return sha256(PARSED_DOCUMENT.dump_json(document, exclude={"structure"})).hexdigest()


def upload_digest(command: UploadDocument, staged_file: StagedFile) -> str:
    payload: str = json.dumps(
        [
            str(command.file_id),
            command.filename,
            command.mime_type,
            staged_file.size,
            staged_file.sha256,
        ]
    )
    return sha256(payload.encode()).hexdigest()

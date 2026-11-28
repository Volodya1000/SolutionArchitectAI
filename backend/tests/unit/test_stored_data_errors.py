from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.chat_errors import StoredDataCorrupt
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.documents.document_models import DocumentUploadRow
from solution_architect_ai.persistence.documents.document_store import upload_view
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import (
    extraction_view,
)
from solution_architect_ai.persistence.models import MessageRow, RunRow
from solution_architect_ai.persistence.queries import run_view


@pytest.mark.parametrize("stored_json", ["{", "{}"])
def test_corrupt_upload_metadata_is_classified_at_deserialization(stored_json: str) -> None:
    row: DocumentUploadRow = DocumentUploadRow(
        operation_id=uuid4(), payload_digest="digest", stage="prepared", version_json=stored_json
    )
    with pytest.raises(DocumentFailure) as raised:
        upload_view(row)
    assert raised.value.code == DocumentErrorCode.CORRUPT_METADATA


@pytest.mark.parametrize("stored_json", ["{", "{}"])
def test_corrupt_extraction_snapshot_is_classified_at_deserialization(stored_json: str) -> None:
    row: ExtractionRow = ExtractionRow(
        id=uuid4(), snapshot_json=stored_json, command_json="{}", created_at=datetime.now(UTC)
    )
    with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
        extraction_view(row)


@pytest.mark.anyio
async def test_corrupt_saved_clarification_command_is_an_extraction_corruption() -> None:
    session: AsyncSession = AsyncSession()
    actor: ActorContext = ActorContext.local(uuid4())
    row: ExtractionRow = ExtractionRow(command_json="{}")
    with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
        await ClarificationQueries(session, actor).resolve_history(row)


def test_corrupt_upload_stage_is_metadata_corruption() -> None:
    row: DocumentUploadRow = DocumentUploadRow(
        operation_id=uuid4(), payload_digest="digest", stage="invalid", version_json="{}"
    )
    with pytest.raises(DocumentFailure) as raised:
        upload_view(row)
    assert raised.value.code == DocumentErrorCode.CORRUPT_METADATA


def test_corrupt_saved_chat_run_status_is_classified_at_read() -> None:
    message: MessageRow = MessageRow(id=uuid4(), content="", position=1, incomplete=True)
    row: RunRow = RunRow(
        id=uuid4(),
        chat_id=uuid4(),
        status="broken",
        sequence=0,
        incomplete=True,
        model="fake-chat",
        config_digest="test",
        error_code=None,
        created_at=datetime.now(UTC),
    )
    with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
        run_view(row, message)

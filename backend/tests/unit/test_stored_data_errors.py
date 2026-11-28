from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from solution_architect_ai.application.errors.chat_errors import StoredDataCorrupt
from solution_architect_ai.application.errors.document_errors import (
    DocumentErrorCode,
    DocumentFailure,
)
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.chat_dto import Preferences
from solution_architect_ai.application.models.clarification_models import ActorContext
from solution_architect_ai.application.models.structured_models import BudgetUsage
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.discussions.models import DiscussionOperationRow
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.documents.document_models import DocumentUploadRow
from solution_architect_ai.persistence.documents.document_store import upload_view
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.extractions.extraction_store import (
    SqlAlchemyExtractionStore,
    extraction_view,
)
from solution_architect_ai.persistence.models import MessageRow, PreferenceRow, RunRow
from solution_architect_ai.persistence.queries import Queries, run_view
from solution_architect_ai.persistence.store import SqlAlchemyStore


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


@pytest.mark.anyio
async def test_corrupt_discussion_replay_is_not_database_unavailability() -> None:
    actor: ActorContext = ActorContext.local(uuid4())
    session: AsyncMock = AsyncMock(spec=AsyncSession)
    session.get.return_value = DiscussionOperationRow(author_id=actor.id, result_json="{}")
    store: SqlAlchemyDiscussionStore = SqlAlchemyDiscussionStore(session, actor)
    with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
        await store.operation(uuid4())


def test_corrupt_upload_stage_is_metadata_corruption() -> None:
    row: DocumentUploadRow = DocumentUploadRow(
        operation_id=uuid4(), payload_digest="digest", stage="invalid", version_json="{}"
    )
    with pytest.raises(DocumentFailure) as raised:
        upload_view(row)
    assert raised.value.code == DocumentErrorCode.CORRUPT_METADATA


@pytest.mark.anyio
async def test_corrupt_saved_preferences_are_not_database_unavailability() -> None:
    session: AsyncMock = AsyncMock(spec=AsyncSession)
    session.get.return_value = PreferenceRow(id=1, theme="invalid")
    with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
        await Queries(session).preferences()


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


@pytest.mark.anyio
async def test_corrupt_saved_chat_status_is_not_an_input_validation_failure() -> None:
    session: AsyncMock = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = RunRow(status="broken")
    with pytest.raises(StoredDataCorrupt, match="stored_data_corrupt"):
        await SqlAlchemyStore(session).set_status(uuid4(), RunStatus.RUNNING)


@pytest.mark.anyio
async def test_corrupt_saved_extraction_status_is_not_an_input_validation_failure() -> None:
    session: AsyncMock = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = ExtractionRow(status="broken")
    with pytest.raises(StoredExtractionCorrupt, match="stored_extraction_corrupt"):
        await SqlAlchemyExtractionStore(session).reserve(uuid4(), BudgetUsage(1, 0, 0), 0)


@pytest.mark.anyio
async def test_invalid_incoming_preferences_are_not_stored_data_corruption() -> None:
    session: AsyncMock = AsyncMock(spec=AsyncSession)
    session.get.return_value = PreferenceRow(id=1, theme="system")
    value: Preferences = Preferences()
    # Simulate a mutable validated DTO changed by a caller before persistence.
    value.__dict__["theme"] = "invalid"
    with pytest.raises(ValidationError):
        await SqlAlchemyStore(session).update_preferences(value)

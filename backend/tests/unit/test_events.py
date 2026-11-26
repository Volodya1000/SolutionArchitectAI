import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import Request
from pydantic import ValidationError

from solution_architect_ai.application import contracts
from solution_architect_ai.application.chat import ChatService
from solution_architect_ai.application.contracts import RunView
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.presentation.routes import events


def run_view() -> RunView:
    return RunView(
        id=UUID("00000000-0000-4000-8000-000000000001"),
        chat_id=UUID("00000000-0000-4000-8000-000000000002"),
        assistant_message_id=UUID("00000000-0000-4000-8000-000000000003"),
        status=RunStatus.COMPLETED,
        sequence=3,
        content="Ответ\n Новая строка",
        incomplete=False,
        error_code=None,
        model="fake",
        config_digest="x",
        created_at=datetime(2026, 11, 26, tzinfo=UTC),
    )


def test_snapshot_contract_serializes_nested_types_and_rejects_unknown_kind() -> None:
    run = run_view()
    event = contracts.RunSnapshotEvent(run_id=run.id, sequence=3, payload=run)
    payload = json.loads(event.model_dump_json())
    assert payload["kind"] == "snapshot"
    assert payload["run_id"] == str(run.id)
    assert payload["payload"]["created_at"] == "2026-11-26T00:00:00Z"
    with pytest.raises(ValidationError):
        contracts.RunSnapshotEvent.model_validate({**payload, "kind": "unknown"})


@pytest.mark.anyio
async def test_terminal_sse_frame_preserves_unicode_and_embedded_newlines() -> None:
    run = run_view()
    service = Mock(spec=ChatService)
    service.run = AsyncMock(return_value=run)
    request = Mock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    frames = [frame async for frame in events(run.id, service, request)]
    assert len(frames) == 1
    assert frames[0].startswith("id: 3\ndata: ")
    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["payload"]["content"] == "Ответ\n Новая строка"
    assert payload["sequence"] == payload["payload"]["sequence"] == 3


@pytest.mark.anyio
async def test_unchanged_active_snapshot_emits_a_heartbeat() -> None:
    run = run_view().model_copy(update={"status": RunStatus.RUNNING})
    service = Mock(spec=ChatService)
    service.run = AsyncMock(return_value=run)
    request = Mock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    stream = events(run.id, service, request)
    await anext(stream)
    assert await anext(stream) == ": heartbeat\n\n"
    await stream.aclose()

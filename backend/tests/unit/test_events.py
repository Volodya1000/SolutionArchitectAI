from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Final, TypedDict, override
from uuid import UUID

import pytest
from fastapi import Request
from pydantic import TypeAdapter, ValidationError

from solution_architect_ai.application.models.chat_dto import RunSnapshotEvent, RunView
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.presentation.routes import events


class SnapshotJSON(TypedDict):
    kind: str
    run_id: str
    payload: dict[str, object]


SERIALIZED_SNAPSHOT: Final[TypeAdapter[SnapshotJSON]] = TypeAdapter(SnapshotJSON)


class SnapshotLookup:
    def __init__(self, snapshot: RunView) -> None:
        self.snapshot: RunView = snapshot

    async def __call__(self, run_id: UUID) -> RunView:
        assert run_id == self.snapshot.id
        return self.snapshot


class ConnectedRequest(Request):
    def __init__(self) -> None:
        super().__init__({"type": "http"})

    @override
    async def is_disconnected(self) -> bool:
        return False


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
    run: RunView = run_view()
    event: RunSnapshotEvent = RunSnapshotEvent(run_id=run.id, sequence=3, payload=run)
    payload: SnapshotJSON = SERIALIZED_SNAPSHOT.validate_json(event.model_dump_json(), strict=True)
    assert payload["kind"] == "snapshot"
    assert payload["run_id"] == str(run.id)
    assert payload["payload"]["created_at"] == "2026-11-26T00:00:00Z"
    with pytest.raises(ValidationError):
        RunSnapshotEvent.model_validate({**payload, "kind": "unknown"})


@pytest.mark.anyio
async def test_terminal_sse_frame_preserves_unicode_and_embedded_newlines() -> None:
    run: RunView = run_view()
    lookup: SnapshotLookup = SnapshotLookup(run)
    request: ConnectedRequest = ConnectedRequest()
    frames: list[str] = [frame async for frame in events(run.id, lookup, request)]
    assert len(frames) == 1
    assert frames[0].startswith("id: 3\ndata: ")
    assert frames[0].endswith("\n\n")
    payload: RunSnapshotEvent = RunSnapshotEvent.model_validate_json(
        frames[0].split("data: ", 1)[1], strict=True
    )
    assert payload.payload.content == "Ответ\n Новая строка"
    assert payload.sequence == payload.payload.sequence == 3


@pytest.mark.anyio
async def test_unchanged_active_snapshot_emits_a_heartbeat() -> None:
    run: RunView = run_view().model_copy(update={"status": RunStatus.RUNNING})
    lookup: SnapshotLookup = SnapshotLookup(run)
    request: ConnectedRequest = ConnectedRequest()
    stream: AsyncGenerator[str] = events(run.id, lookup, request)
    await anext(stream)
    assert await anext(stream) == ": heartbeat\n\n"
    await stream.aclose()

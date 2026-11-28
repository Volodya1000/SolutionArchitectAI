import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Final, Literal
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from backend.test_helpers.clarification_http import (
    HttpCase,
    SqlSnapshot,
    actor_client,
    answer_command,
    application,
    sql_snapshot,
)
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    AnswerClarification,
    DecisionResult,
    SourceVersion,
)
from solution_architect_ai.application.models.extraction_models import (
    RequirementView,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


class DropCommittedResponse(httpx.AsyncBaseTransport):
    def __init__(self, app: FastAPI) -> None:
        self.inner: httpx.ASGITransport = httpx.ASGITransport(app=app)
        self.committed_body: bytes | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response: httpx.Response = await self.inner.handle_async_request(request)
        if request.method == "POST" and self.committed_body is None:
            # ASGI has finished, including the store context manager's SQL commit.
            assert response.status_code == 200
            self.committed_body = await response.aread()
            await response.aclose()
            raise httpx.ReadError("response lost after server commit", request=request)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def assert_race_commit(
    commands: list[AnswerClarification],
    responses: list[httpx.Response],
    before: SqlSnapshot,
    after: SqlSnapshot,
) -> AnswerClarification:
    assert sorted(response.status_code for response in responses) == [200, 409]
    winning_index: int = next(
        index for index, response in enumerate(responses) if response.status_code == 200
    )
    winner: AnswerClarification = commands[winning_index]
    loser: AnswerClarification = commands[1 - winning_index]
    decision: DecisionResult = DecisionResult.model_validate_json(responses[winning_index].content)
    assert responses[1 - winning_index].json() == {"code": "stale_question_revision"}
    assert after.view.decisions == [decision]
    assert len(after.decisions) == 1
    assert len(after.risks) == len(after.view.risks) == (1 if winner.kind == "assumption" else 0)
    assert after.view.questions[0].status == (
        "assumed" if winner.kind == "assumption" else "answered"
    )
    assert after.view.resume_pending
    assert after.view.resume_version == before.view.resume_version + 1
    assert [operation_id for operation_id, _result in after.operations] == [winner.operation_id]
    requirement: RequirementView = next(
        item for item in after.view.requirements if item.id in decision.requirement_ids
    )
    assert winner.text in requirement.normalized_text
    assert all(loser.text not in item.normalized_text for item in after.view.requirements)
    return winner


async def race_verified_requests(
    case: HttpCase,
    client: httpx.AsyncClient,
    commands: list[AnswerClarification],
    monkeypatch: pytest.MonkeyPatch,
) -> list[httpx.Response]:
    barrier: asyncio.Barrier = asyncio.Barrier(2)
    original: Callable[[list[SourceVersion]], Awaitable[None]] = case.service.verify_versions

    async def verified_together(sources: list[SourceVersion]) -> None:
        await original(sources)
        await barrier.wait()

    monkeypatch.setattr(case.service, "verify_versions", verified_together)
    try:
        async with asyncio.timeout(10):
            return list(
                await asyncio.gather(
                    *(
                        client.post(case.answer_url, json=command.model_dump(mode="json"))
                        for command in commands
                    )
                )
            )
    finally:
        monkeypatch.setattr(case.service, "verify_versions", original)


@pytest.mark.parametrize("assumption_first", [False, True])
async def test_http_answer_and_assumption_race_has_one_committed_winner(
    http_case: HttpCase, monkeypatch: pytest.MonkeyPatch, assumption_first: bool
) -> None:
    commands: list[AnswerClarification] = [
        answer_command(http_case, assumption=assumption_first),
        answer_command(http_case, assumption=not assumption_first),
    ]
    operation_ids: list[UUID] = [command.operation_id for command in commands]
    before: SqlSnapshot = await sql_snapshot(http_case, operation_ids)
    client: httpx.AsyncClient
    _attempt: int
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(http_case.resources.container)),
        base_url="http://test",
    ) as client:
        responses: list[httpx.Response] = await race_verified_requests(
            http_case, client, commands, monkeypatch
        )
        after: SqlSnapshot = await sql_snapshot(http_case, operation_ids)
        winner: AnswerClarification = assert_race_commit(commands, responses, before, after)
        for _attempt in range(3):
            replay: httpx.Response = await client.post(
                http_case.answer_url, json=winner.model_dump(mode="json")
            )
            assert replay.status_code == 200
            assert DecisionResult.model_validate_json(replay.content) == after.view.decisions[0]
        loser: AnswerClarification = next(
            command for command in commands if command.operation_id != winner.operation_id
        )
        missing: httpx.Response = await client.get(
            f"/api/clarification-operations/{loser.operation_id}"
        )
        assert missing.status_code == 404
        assert await sql_snapshot(http_case, operation_ids) == after


async def test_http_lost_committed_response_replays_after_source_disappears(
    http_case: HttpCase,
) -> None:
    command: AnswerClarification = answer_command(http_case, assumption=True)
    transport: DropCommittedResponse = DropCommittedResponse(
        application(http_case.resources.container)
    )
    client: httpx.AsyncClient
    _attempt: int
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="response lost after server commit"):
            await client.post(http_case.answer_url, json=command.model_dump(mode="json"))
        committed: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
        assert len(committed.decisions) == len(committed.risks) == len(committed.operations) == 1
        assert committed.view.resume_pending
        assert committed.view.resume_version == 1
        assert transport.committed_body is not None
        assert (
            DecisionResult.model_validate_json(transport.committed_body)
            == committed.view.decisions[0]
        )
        await asyncio.to_thread(
            (http_case.resources.settings.storage.root / http_case.version.storage_key).unlink
        )
        for _attempt in range(3):
            replay: httpx.Response = await client.post(
                http_case.answer_url, json=command.model_dump(mode="json")
            )
            assert replay.status_code == 200
            assert replay.content == transport.committed_body
        operation: httpx.Response = await client.get(
            f"/api/clarification-operations/{command.operation_id}"
        )
        assert operation.status_code == 200
        assert operation.content == transport.committed_body
        changed: AnswerClarification = command.model_copy(update={"text": "Изменённое решение"})
        conflict: httpx.Response = await client.post(
            http_case.answer_url, json=changed.model_dump(mode="json")
        )
        assert conflict.status_code == 409
        assert conflict.json() == {"code": "operation_payload_changed"}
        assert await sql_snapshot(http_case, [command.operation_id]) == committed


@pytest.mark.parametrize(
    ("rejection", "status", "code"),
    [
        ("stale", 409, "stale_question_revision"),
        ("source", 409, "source_versions_changed"),
        ("foreign", 404, "not_found"),
        ("readonly", 403, "permission_denied"),
    ],
)
async def test_http_rejected_answer_leaves_question_requirements_and_resume_unchanged(
    http_case: HttpCase,
    rejection: Literal["stale", "source", "foreign", "readonly"],
    status: int,
    code: str,
) -> None:
    command: AnswerClarification = answer_command(http_case, assumption=True)
    actor: ActorContext = http_case.stores.actor
    if rejection == "stale":
        command = command.model_copy(update={"expected_question_revision": 2})
    elif rejection == "source":
        command = command.model_copy(
            update={
                "source_versions": [
                    SourceVersion(version_id=http_case.version.version_id, sha256="0" * 64)
                ]
            }
        )
    elif rejection == "foreign":
        actor = replace(actor, task_id=uuid4())
    else:
        actor = replace(actor, can_write=False)
    before: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
    client: httpx.AsyncClient
    async with actor_client(http_case, actor) as client:
        response: httpx.Response = await client.post(
            http_case.answer_url, json=command.model_dump(mode="json")
        )
    assert response.status_code == status
    assert response.json() == {"code": code}
    assert await sql_snapshot(http_case, [command.operation_id]) == before
    assert not before.decisions
    assert not before.risks
    assert not before.operations
    assert not before.view.resume_pending
    assert before.view.questions[0].status == "open"

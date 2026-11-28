import asyncio
import os
from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from solution_architect_ai.application.models.chat_dto import (
    ChatSnapshot,
    ChatView,
    Preferences,
    RunView,
)
from solution_architect_ai.di.main import create_app
from solution_architect_ai.domain.runs import RunStatus

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture(name="client")
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test"), (
        "Use a dedicated _test database"
    )
    app: FastAPI = create_app()
    http: httpx.AsyncClient
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def new_chat(client: httpx.AsyncClient) -> UUID:
    result: httpx.Response = await client.post("/api/chats", json={"title": "Новый диалог"})
    assert result.status_code == 201
    return ChatView.model_validate_json(result.content, strict=True).id


async def chat_history(client: httpx.AsyncClient, chat_id: UUID) -> ChatSnapshot:
    response: httpx.Response = await client.get(f"/api/chats/{chat_id}")
    return ChatSnapshot.model_validate_json(response.content, strict=True)


async def wait_terminal(client: httpx.AsyncClient, run_id: UUID) -> RunView:
    async with asyncio.timeout(15):
        while True:
            response: httpx.Response = await client.get(f"/api/runs/{run_id}")
            assert response.status_code == 200
            run: RunView = RunView.model_validate_json(response.content, strict=True)
            if run.status.terminal:
                return run
            await asyncio.sleep(0.03)


async def test_two_chats_persist_independent_history_and_replay_start(
    client: httpx.AsyncClient,
) -> None:
    first: UUID = await new_chat(client)
    second: UUID = await new_chat(client)
    body: dict[str, str] = {"command_id": str(uuid4()), "content": "Привет"}
    started: httpx.Response = await client.post(f"/api/chats/{first}/runs", json=body)
    assert started.status_code == 202
    run_id: UUID = RunView.model_validate_json(started.content, strict=True).id
    repeated: httpx.Response = await client.post(f"/api/chats/{first}/runs", json=body)
    assert RunView.model_validate_json(repeated.content, strict=True).id == run_id
    result: RunView = await wait_terminal(client, run_id)
    assert result.status == RunStatus.COMPLETED
    assert result.incomplete is False
    assert result.content
    assert len(result.config_digest) == 64
    first_history: ChatSnapshot = await chat_history(client, first)
    second_history: ChatSnapshot = await chat_history(client, second)
    assert len(first_history.messages) == 2
    assert not second_history.messages
    conflict: httpx.Response = await client.post(
        f"/api/chats/{first}/runs", json={**body, "content": "Другая команда"}
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize("prompt", ["[error]", "[empty]", "[truncated]", "[disconnect]"])
async def test_llm_failure_never_becomes_a_complete_answer(
    client: httpx.AsyncClient, prompt: str
) -> None:
    chat: UUID = await new_chat(client)
    started: httpx.Response = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": prompt}
    )
    run_id: UUID = RunView.model_validate_json(started.content, strict=True).id
    result: RunView = await wait_terminal(client, run_id)
    assert result.status == RunStatus.FAILED
    assert result.incomplete is True
    assert result.error_code


async def test_server_cancel_is_idempotent_and_preserves_partial_output(
    client: httpx.AsyncClient,
) -> None:
    chat: UUID = await new_chat(client)
    started: httpx.Response = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": "[slow]"}
    )
    run_id: UUID = RunView.model_validate_json(started.content, strict=True).id
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 200
    result: RunView = await wait_terminal(client, run_id)
    assert result.status == RunStatus.CANCELLED
    assert result.incomplete is True
    repeated: httpx.Response = await client.post(f"/api/runs/{run_id}/cancel")
    assert RunView.model_validate_json(repeated.content, strict=True).status == RunStatus.CANCELLED


async def test_unknown_chat_and_invalid_input_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/api/chats/{uuid4()}")).status_code == 404
    chat: UUID = await new_chat(client)
    response: httpx.Response = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": " "}
    )
    assert response.status_code == 422
    assert [(item["loc"], item["type"]) for item in response.json()["detail"]] == [
        (["body", "content"], "string_too_short")
    ]


async def test_theme_is_stored_in_postgres(client: httpx.AsyncClient) -> None:
    response: httpx.Response = await client.put("/api/preferences", json={"theme": "dark"})
    assert response.status_code == 200
    saved: httpx.Response = await client.get("/api/preferences")
    assert Preferences.model_validate_json(saved.content, strict=True).theme == "dark"
    await client.put("/api/preferences", json={"theme": "system"})


async def test_model_availability_is_separate_from_history(client: httpx.AsyncClient) -> None:
    response: httpx.Response = await client.get("/api/model")
    assert response.status_code == 200
    payload: object = response.json()
    assert payload == {"model": "fake-chat", "available": True}
    assert (await client.get("/api/chats")).status_code == 200


async def test_parallel_replay_creates_one_run(client: httpx.AsyncClient) -> None:
    chat: UUID = await new_chat(client)
    command: dict[str, str] = {"command_id": str(uuid4()), "content": "Конкурентный повтор"}
    first: httpx.Response
    second: httpx.Response
    first, second = await asyncio.gather(
        client.post(f"/api/chats/{chat}/runs", json=command),
        client.post(f"/api/chats/{chat}/runs", json=command),
    )
    assert first.status_code == second.status_code == 202
    first_run: UUID = RunView.model_validate_json(first.content, strict=True).id
    assert first_run == RunView.model_validate_json(second.content, strict=True).id
    await wait_terminal(client, first_run)
    snapshot: ChatSnapshot = await chat_history(client, chat)
    assert len(snapshot.runs) == 1
    assert len(snapshot.messages) == 2


async def test_shutdown_and_restart_preserve_partial_history_without_replaying() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    app: FastAPI = create_app()
    http: httpx.AsyncClient
    command: dict[str, str] = {"command_id": str(uuid4()), "content": "[slow] restart"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        chat: UUID = await new_chat(http)
        started: httpx.Response = await http.post(f"/api/chats/{chat}/runs", json=command)
        run_id: UUID = RunView.model_validate_json(started.content, strict=True).id
        async with asyncio.timeout(5):
            while True:
                response: httpx.Response = await http.get(f"/api/runs/{run_id}")
                current: RunView = RunView.model_validate_json(response.content, strict=True)
                if current.content:
                    break
                await asyncio.sleep(0.02)
    restarted: FastAPI = create_app()
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as http,
    ):
        restored: httpx.Response = await http.get(f"/api/runs/{run_id}")
        run: RunView = RunView.model_validate_json(restored.content, strict=True)
        assert run.status == RunStatus.FAILED
        assert run.incomplete is True
        assert run.content
        replay: httpx.Response = await http.post(f"/api/chats/{chat}/runs", json=command)
        assert RunView.model_validate_json(replay.content, strict=True).id == run_id
        assert len((await chat_history(http, chat)).messages) == 2

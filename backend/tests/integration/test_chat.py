import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from solution_architect_ai.di.main import create_app

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test"), (
        "Use a dedicated _test database"
    )
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        yield http


async def new_chat(client: httpx.AsyncClient) -> str:
    result = await client.post("/api/chats", json={"title": "Новый диалог"})
    assert result.status_code == 201
    return str(result.json()["id"])


async def wait_terminal(client: httpx.AsyncClient, run_id: str) -> dict[str, object]:
    async with asyncio.timeout(15):
        while True:
            response = await client.get(f"/api/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            if data["status"] in {"completed", "failed", "cancelled"}:
                return dict(data)
            await asyncio.sleep(0.03)


async def test_two_chats_persist_independent_history_and_replay_start(
    client: httpx.AsyncClient,
) -> None:
    first, second = await new_chat(client), await new_chat(client)
    body = {"command_id": str(uuid4()), "content": "Привет"}
    started = await client.post(f"/api/chats/{first}/runs", json=body)
    assert started.status_code == 202
    run_id = started.json()["id"]
    repeated = await client.post(f"/api/chats/{first}/runs", json=body)
    assert repeated.json()["id"] == run_id
    result = await wait_terminal(client, run_id)
    assert result["status"] == "completed"
    assert result["incomplete"] is False
    assert result["content"]
    assert len(str(result["config_digest"])) == 64
    history = (await client.get(f"/api/chats/{first}")).json()
    assert len(history["messages"]) == 2
    assert (await client.get(f"/api/chats/{second}")).json()["messages"] == []
    conflict = await client.post(
        f"/api/chats/{first}/runs", json={**body, "content": "Другая команда"}
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize("prompt", ["[error]", "[empty]", "[truncated]", "[disconnect]"])
async def test_llm_failure_never_becomes_a_complete_answer(
    client: httpx.AsyncClient, prompt: str
) -> None:
    chat = await new_chat(client)
    started = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": prompt}
    )
    result = await wait_terminal(client, started.json()["id"])
    assert result["status"] == "failed"
    assert result["incomplete"] is True
    assert result["error_code"]


async def test_server_cancel_is_idempotent_and_preserves_partial_output(
    client: httpx.AsyncClient,
) -> None:
    chat = await new_chat(client)
    started = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": "[slow]"}
    )
    run_id = started.json()["id"]
    assert (await client.post(f"/api/runs/{run_id}/cancel")).status_code == 200
    result = await wait_terminal(client, run_id)
    assert result["status"] == "cancelled"
    assert result["incomplete"] is True
    assert (await client.post(f"/api/runs/{run_id}/cancel")).json()["status"] == "cancelled"


async def test_unknown_chat_and_invalid_input_are_rejected(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/api/chats/{uuid4()}")).status_code == 404
    chat = await new_chat(client)
    response = await client.post(
        f"/api/chats/{chat}/runs", json={"command_id": str(uuid4()), "content": " "}
    )
    assert response.status_code == 422


async def test_theme_is_stored_in_postgres(client: httpx.AsyncClient) -> None:
    response = await client.put("/api/preferences", json={"theme": "dark"})
    assert response.status_code == 200
    assert (await client.get("/api/preferences")).json()["theme"] == "dark"
    await client.put("/api/preferences", json={"theme": "system"})


async def test_model_availability_is_separate_from_history(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/model")
    assert response.status_code == 200
    assert response.json() == {"model": "fake-chat", "available": True}
    assert (await client.get("/api/chats")).status_code == 200


async def test_parallel_replay_creates_one_run(client: httpx.AsyncClient) -> None:
    chat = await new_chat(client)
    command = {"command_id": str(uuid4()), "content": "Конкурентный повтор"}
    first, second = await asyncio.gather(
        client.post(f"/api/chats/{chat}/runs", json=command),
        client.post(f"/api/chats/{chat}/runs", json=command),
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    await wait_terminal(client, first.json()["id"])
    snapshot = (await client.get(f"/api/chats/{chat}")).json()
    assert len(snapshot["runs"]) == 1
    assert len(snapshot["messages"]) == 2


async def test_shutdown_and_restart_preserve_partial_history_without_replaying() -> None:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    app = create_app()
    command = {"command_id": str(uuid4()), "content": "[slow] restart"}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
    ):
        chat = await new_chat(http)
        started = await http.post(f"/api/chats/{chat}/runs", json=command)
        run_id = started.json()["id"]
        async with asyncio.timeout(5):
            while True:
                current = (await http.get(f"/api/runs/{run_id}")).json()
                if current["content"]:
                    break
                await asyncio.sleep(0.02)
    restarted = create_app()
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as http,
    ):
        run = (await http.get(f"/api/runs/{run_id}")).json()
        assert run["status"] == "failed"
        assert run["incomplete"] is True
        assert run["content"]
        replay = await http.post(f"/api/chats/{chat}/runs", json=command)
        assert replay.json()["id"] == run_id
        assert len((await http.get(f"/api/chats/{chat}")).json()["messages"]) == 2

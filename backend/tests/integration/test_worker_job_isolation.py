import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.test_helpers.worker_http import (
    create_chat,
    independent_analysis,
    start_chat,
    terminal_run,
)
from solution_architect_ai.application.models.chat_dto import RunView
from solution_architect_ai.di.main import create_app
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus
from solution_architect_ai.persistence.discussions.models import DiscussionRow
from solution_architect_ai.persistence.store import SqlAlchemyStore

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture(name="queue_app")
async def queue_app_fixture() -> AsyncIterator[FastAPI]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    app: FastAPI = create_app()
    async with app.router.lifespan_context(app):
        yield app


async def test_corrupt_discussion_job_is_terminal_without_stopping_neighbors(
    queue_app: FastAPI,
) -> None:
    sessions: async_sessionmaker[AsyncSession] = await queue_app.state.dishka_container.get(
        async_sessionmaker[AsyncSession]
    )
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=queue_app), base_url="http://test"
    ) as client:
        broken_chat: UUID = await create_chat(client)
        session: AsyncSession
        async with sessions.begin() as session:
            session.add(DiscussionRow(chat_id=broken_chat, binding_json="{"))
        broken: RunView = await start_chat(client, broken_chat)
        failed: RunView = await terminal_run(client, broken.id)
        assert failed.status == RunStatus.FAILED
        assert failed.error_code is not None
        assert failed.error_code == "stored_data_corrupt"
        assert failed.incomplete is True
        neighbor: RunView = await start_chat(client, await create_chat(client))
        assert (await terminal_run(client, neighbor.id)).status == RunStatus.COMPLETED
        assert (await client.get("/api/health/ready")).status_code == 200
        await independent_analysis(client)


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
async def test_one_claim_transaction_conflict_rolls_back_and_queue_keeps_working(
    queue_app: FastAPI, monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    original_set_status: Callable[
        [SqlAlchemyStore, UUID, RunStatus, RunErrorCode | None], Awaitable[RunView]
    ] = SqlAlchemyStore.set_status
    injected: bool = False

    async def conflicting_claim(
        store: SqlAlchemyStore,
        run_id: UUID,
        target: RunStatus,
        error: RunErrorCode | None = None,
    ) -> RunView:
        nonlocal injected
        result: RunView = await original_set_status(store, run_id, target, error)
        if target == RunStatus.RUNNING and not injected:
            injected = True
            await store.session.execute(
                text(
                    "DO $$ BEGIN RAISE EXCEPTION 'controlled conflict' USING ERRCODE = '"
                    + sqlstate
                    + "'; END $$"
                )
            )
        return result

    monkeypatch.setattr(SqlAlchemyStore, "set_status", conflicting_claim)
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=queue_app), base_url="http://test"
    ) as client:
        first: RunView = await start_chat(client, await create_chat(client))
        assert (await terminal_run(client, first.id)).status == RunStatus.COMPLETED
        second: RunView = await start_chat(client, await create_chat(client))
        assert (await terminal_run(client, second.id)).status == RunStatus.COMPLETED
        assert (await client.get("/api/health/ready")).status_code == 200
        await independent_analysis(client)


async def test_readiness_rejects_a_lost_required_worker(queue_app: FastAPI) -> None:
    task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
    await task
    queue_app.state.worker_tasks = [task]
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=queue_app), base_url="http://test"
    ) as client:
        response: httpx.Response = await client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json() == {"code": "required_worker_unavailable"}

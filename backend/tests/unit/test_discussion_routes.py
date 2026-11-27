from typing import Final

import httpx
import pytest
from fastapi import FastAPI

from solution_architect_ai.di.main import create_app
from solution_architect_ai.presentation.discussion_routes import router

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio]


async def test_discussion_route_validates_server_owned_subject() -> None:
    app: FastAPI = create_app()
    app.include_router(router)
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response: httpx.Response = await client.post("/api/discussions", json={})
    assert response.status_code == 422

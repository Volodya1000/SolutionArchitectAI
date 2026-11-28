from typing import Final
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from solution_architect_ai.di.main import create_app

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio]


@pytest.mark.parametrize(
    ("subject", "expected_type"),
    [(None, "missing"), ({"kind": "invented"}, "union_tag_invalid")],
)
async def test_discussion_route_validates_server_owned_subject(
    subject: dict[str, str] | None, expected_type: str
) -> None:
    app: FastAPI = create_app()
    body: dict[str, object] = {"operation_id": str(uuid4())}
    if subject is not None:
        body["subject"] = subject
    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response: httpx.Response = await client.post("/api/discussions", json=body)
    assert response.status_code == 422
    assert [(error["loc"], error["type"]) for error in response.json()["detail"]] == [
        (["body", "subject"], expected_type)
    ]

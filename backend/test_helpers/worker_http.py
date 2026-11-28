import asyncio
from uuid import UUID, uuid4

import httpx

from solution_architect_ai.application.models.chat_dto import ChatView, RunView
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import ExtractionView
from solution_architect_ai.domain.runs import RunStatus


async def create_chat(client: httpx.AsyncClient) -> UUID:
    response: httpx.Response = await client.post("/api/chats", json={"title": "Queue regression"})
    assert response.status_code == 201
    return ChatView.model_validate_json(response.content).id


async def start_chat(client: httpx.AsyncClient, chat_id: UUID) -> RunView:
    response: httpx.Response = await client.post(
        f"/api/chats/{chat_id}/runs", json={"command_id": str(uuid4()), "content": "Hello"}
    )
    assert response.status_code == 202
    return RunView.model_validate_json(response.content)


async def terminal_run(client: httpx.AsyncClient, run_id: UUID) -> RunView:
    async with asyncio.timeout(15):
        while True:
            response: httpx.Response = await client.get(f"/api/runs/{run_id}")
            assert response.status_code == 200
            run: RunView = RunView.model_validate_json(response.content)
            if run.status.terminal:
                return run
            await asyncio.sleep(0.03)


async def independent_analysis(client: httpx.AsyncClient) -> None:
    uploaded: httpx.Response = await client.post(
        "/api/documents",
        params={"operation_id": str(uuid4()), "filename": "queue-neighbor.md"},
        content=b"The system shall retain records.",
        headers={"Content-Type": "text/markdown"},
    )
    assert uploaded.status_code == 201
    version: DocumentVersionView = DocumentVersionView.model_validate_json(uploaded.content)
    started: httpx.Response = await client.post(
        "/api/extractions",
        json={
            "operation_id": str(uuid4()),
            "version_ids": [str(version.version_id)],
            "answer_history_mode": "new",
        },
    )
    assert started.status_code == 202
    run: ExtractionView = ExtractionView.model_validate_json(started.content)
    async with asyncio.timeout(30):
        while True:
            response: httpx.Response = await client.get(f"/api/extractions/{run.id}")
            assert response.status_code == 200
            run = ExtractionView.model_validate_json(response.content)
            if run.status.terminal or run.status == RunStatus.WAITING_INPUT:
                break
            await asyncio.sleep(0.03)
    assert run.status in {RunStatus.COMPLETED, RunStatus.WAITING_INPUT}
    assert run.requirements

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from solution_architect_ai.application.chat import ChatService
from solution_architect_ai.application.contracts import (
    ChatCreate,
    ChatSnapshot,
    ChatView,
    ModelStatus,
    Preferences,
    RunSnapshotEvent,
    RunView,
    StartRun,
)
from solution_architect_ai.application.ports import LLM

router = APIRouter(prefix="/api", route_class=DishkaRoute)


@router.get("/model")
async def model_status(llm: FromDishka[LLM]) -> ModelStatus:
    return await llm.status()


@router.get("/chats")
async def chats(service: FromDishka[ChatService]) -> list[ChatView]:
    return await service.list_chats()


@router.post("/chats", status_code=201)
async def create_chat(body: ChatCreate, service: FromDishka[ChatService]) -> ChatView:
    return await service.create(body.title)


@router.get("/chats/{chat_id}")
async def snapshot(chat_id: UUID, service: FromDishka[ChatService]) -> ChatSnapshot:
    return await service.snapshot(chat_id)


@router.post("/chats/{chat_id}/runs", status_code=202)
async def start(chat_id: UUID, body: StartRun, service: FromDishka[ChatService]) -> RunView:
    return await service.start(chat_id, body)


@router.get("/runs/{run_id}")
async def run(run_id: UUID, service: FromDishka[ChatService]) -> RunView:
    return await service.run(run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: UUID, service: FromDishka[ChatService]) -> RunView:
    return await service.cancel(run_id)


def _format_sse_data(event_id: int | str, data: str) -> str:
    return f"id: {event_id}\ndata: {data}\n\n"


def _format_sse_comment(comment: str) -> str:
    return f": {comment}\n\n"


async def events(run_id: UUID, service: ChatService, request: Request) -> AsyncIterator[str]:
    sequence = -1
    while not await request.is_disconnected():
        current = await service.run(run_id)
        if current.sequence > sequence:
            sequence = current.sequence
            event = RunSnapshotEvent(run_id=run_id, sequence=sequence, payload=current)
            yield _format_sse_data(sequence, event.model_dump_json())
        if current.status.terminal:
            return
        yield _format_sse_comment("heartbeat")
        await asyncio.sleep(0.15)


@router.get("/runs/{run_id}/events")
async def stream(
    run_id: UUID, request: Request, service: FromDishka[ChatService]
) -> StreamingResponse:
    await service.run(run_id)
    return StreamingResponse(
        events(run_id, service, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/preferences")
async def preferences(service: FromDishka[ChatService]) -> Preferences:
    return await service.preferences()


@router.put("/preferences")
async def save_preferences(body: Preferences, service: FromDishka[ChatService]) -> Preferences:
    return await service.update_preferences(body)


@router.get("/health/ready")
async def ready(service: FromDishka[ChatService]) -> dict[str, str]:
    await service.ready()
    return {"status": "ready"}


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}

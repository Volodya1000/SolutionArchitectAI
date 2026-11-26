import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from solution_architect_ai.application.chat import ChatService
from solution_architect_ai.application.dto import (
    APIError,
    ChatCreate,
    ChatSnapshot,
    ChatView,
    HealthStatus,
    ModelStatus,
    Preferences,
    RunSnapshotEvent,
    RunView,
    StartRun,
)
from solution_architect_ai.application.ports import LLM, ChatStore, StoreFactory

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)


@router.get("/model")
async def model_status(llm: FromDishka[LLM]) -> ModelStatus:
    return await llm.status()


@router.get("/chats", responses={503: {"model": APIError}})
async def chats(stores: FromDishka[StoreFactory]) -> list[ChatView]:
    store: ChatStore
    async with stores.open() as store:
        return await store.queries.list_chats()


@router.post("/chats", status_code=201, responses={503: {"model": APIError}})
async def create_chat(body: ChatCreate, stores: FromDishka[StoreFactory]) -> ChatView:
    store: ChatStore
    async with stores.open() as store:
        return await store.create_chat(body.title)


@router.get("/chats/{chat_id}", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def snapshot(chat_id: UUID, stores: FromDishka[StoreFactory]) -> ChatSnapshot:
    store: ChatStore
    async with stores.open() as store:
        return await store.queries.snapshot(chat_id)


@router.post(
    "/chats/{chat_id}/runs",
    status_code=202,
    responses={404: {"model": APIError}, 409: {"model": APIError}, 503: {"model": APIError}},
)
async def start(chat_id: UUID, body: StartRun, service: FromDishka[ChatService]) -> RunView:
    return await service.start(chat_id, body)


@router.get("/runs/{run_id}", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def run(run_id: UUID, service: FromDishka[ChatService]) -> RunView:
    return await service.run(run_id)


@router.post(
    "/runs/{run_id}/cancel", responses={404: {"model": APIError}, 503: {"model": APIError}}
)
async def cancel(run_id: UUID, service: FromDishka[ChatService]) -> RunView:
    return await service.cancel(run_id)


def _format_sse_data(event_id: int | str, data: str) -> str:
    return f"id: {event_id}\ndata: {data}\n\n"


def _format_sse_comment(comment: str) -> str:
    return f": {comment}\n\n"


async def events(
    run_id: UUID, lookup: Callable[[UUID], Awaitable[RunView]], request: Request
) -> AsyncGenerator[str]:
    sequence: int = -1
    while not await request.is_disconnected():
        current: RunView = await lookup(run_id)
        if current.sequence > sequence:
            sequence = current.sequence
            event: RunSnapshotEvent = RunSnapshotEvent(
                run_id=run_id, sequence=sequence, payload=current
            )
            yield _format_sse_data(sequence, event.model_dump_json())
        if current.status.terminal:
            return
        yield _format_sse_comment("heartbeat")
        await asyncio.sleep(0.15)


@router.get("/runs/{run_id}/events", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def stream(
    run_id: UUID, request: Request, service: FromDishka[ChatService]
) -> StreamingResponse:
    await service.run(run_id)
    return StreamingResponse(
        events(run_id, service.run, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/preferences", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def preferences(stores: FromDishka[StoreFactory]) -> Preferences:
    store: ChatStore
    async with stores.open() as store:
        return await store.queries.preferences()


@router.put("/preferences", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def save_preferences(body: Preferences, stores: FromDishka[StoreFactory]) -> Preferences:
    store: ChatStore
    async with stores.open() as store:
        return await store.update_preferences(body)


@router.get("/health/ready", responses={503: {"model": APIError}})
async def ready(service: FromDishka[ChatService]) -> HealthStatus:
    await service.ready()
    return HealthStatus(status="ready")


@router.get("/health/live")
async def live() -> HealthStatus:
    return HealthStatus(status="alive")

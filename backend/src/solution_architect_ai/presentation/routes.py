import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from solution_architect_ai.application.models.chat_dto import (
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
from solution_architect_ai.application.protocols.chat_protocols import LLM, ChatStore
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.chat_service import ChatService

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)


class EventStreamResponse(StreamingResponse):
    media_type: str = "text/event-stream"


@router.get("/model")
async def model_status(llm: FromDishka[LLM]) -> ModelStatus:
    return await llm.status()


@router.get("/chats", responses={503: {"model": APIError}})
async def chats(stores: FromDishka[StoreContext[ChatStore]]) -> list[ChatView]:
    store: ChatStore
    async with stores.open() as store:
        return await store.queries.list_chats()


@router.post("/chats", status_code=201, responses={503: {"model": APIError}})
async def create_chat(body: ChatCreate, stores: FromDishka[StoreContext[ChatStore]]) -> ChatView:
    store: ChatStore
    async with stores.open() as store:
        return await store.create_chat(body.title)


@router.get("/chats/{chat_id}", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def snapshot(chat_id: UUID, stores: FromDishka[StoreContext[ChatStore]]) -> ChatSnapshot:
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


@router.get(
    "/runs/{run_id}/events",
    response_class=EventStreamResponse,
    response_model=RunSnapshotEvent,
    responses={404: {"model": APIError}, 503: {"model": APIError}},
)
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
async def preferences(stores: FromDishka[StoreContext[ChatStore]]) -> Preferences:
    store: ChatStore
    async with stores.open() as store:
        return await store.queries.preferences()


@router.put("/preferences", responses={404: {"model": APIError}, 503: {"model": APIError}})
async def save_preferences(
    body: Preferences, stores: FromDishka[StoreContext[ChatStore]]
) -> Preferences:
    store: ChatStore
    async with stores.open() as store:
        return await store.update_preferences(body)


@router.get("/health/ready", response_model=HealthStatus, responses={503: {"model": APIError}})
async def ready(service: FromDishka[ChatService], request: Request) -> HealthStatus | JSONResponse:
    tasks: list[asyncio.Task[None]] = getattr(request.app.state, "worker_tasks", [])
    if any(task.done() for task in tasks):
        return JSONResponse(status_code=503, content={"code": "required_worker_unavailable"})
    await service.ready()
    return HealthStatus(status="ready")


@router.get("/health/live")
async def live() -> HealthStatus:
    return HealthStatus(status="alive")

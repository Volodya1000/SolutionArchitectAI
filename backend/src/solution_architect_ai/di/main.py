import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from solution_architect_ai.application.dto import APIError
from solution_architect_ai.application.errors import ChatError, Conflict, Missing
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.config.models import Mode
from solution_architect_ai.config.settings import Settings, load_settings
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.presentation.routes import router


async def chat_error(_request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, Missing):
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND, content=APIError(code="not_found").model_dump()
        )
    if isinstance(error, Conflict):
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT, content=APIError(code="conflict").model_dump()
        )
    return JSONResponse(
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        content=APIError(code="database_unavailable").model_dump(),
    )


def bootstrap() -> Settings:
    root: Path = Path(os.environ.get("SAA_CONFIG_ROOT", ".")).resolve()
    try:
        mode: Mode = TypeAdapter(Mode).validate_python(os.environ.get("SAA_MODE", "production"))
    except ValidationError:
        raise ValueError("Invalid bootstrap mode") from None
    return load_settings(root, mode)


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings: Settings = bootstrap()
    container: AsyncContainer = make_async_container(AppProvider(), context={Settings: settings})

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker: RunWorker = await container.get(RunWorker)
        try:
            await worker.recover()
            group: asyncio.TaskGroup
            async with asyncio.TaskGroup() as group:
                group.create_task(worker.serve())
                try:
                    yield
                finally:
                    worker.stopping.set()
        finally:
            await container.close()

    app: FastAPI = FastAPI(title="SolutionArchitectAI", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.add_exception_handler(ChatError, chat_error)
    setup_dishka(container, app)
    return app

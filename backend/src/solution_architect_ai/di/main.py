import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from solution_architect_ai.application.contracts import ChatError, Conflict, Missing
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.config.models import Mode
from solution_architect_ai.config.settings import Settings, load_settings
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.presentation.routes import router


async def chat_error(_request: Request, error: Exception) -> JSONResponse:
    status = 404 if isinstance(error, Missing) else 409 if isinstance(error, Conflict) else 503
    code = "not_found" if status == 404 else "conflict" if status == 409 else "database_unavailable"
    return JSONResponse(status_code=status, content={"code": code})


def bootstrap() -> Settings:
    root = Path(os.environ.get("SAA_CONFIG_ROOT", ".")).resolve()
    mode = os.environ.get("SAA_MODE", "production")
    if mode not in {"development", "test", "production"}:
        raise ValueError("Invalid bootstrap mode")
    return load_settings(root, cast(Mode, mode))


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = bootstrap()
    container = make_async_container(AppProvider(), context={Settings: settings})

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker = await container.get(RunWorker)
        try:
            await worker.recover()
            async with asyncio.TaskGroup() as group:
                group.create_task(worker.serve())
                try:
                    yield
                finally:
                    worker.stopping.set()
        finally:
            await container.close()

    app = FastAPI(title="SolutionArchitectAI", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.add_exception_handler(ChatError, chat_error)
    setup_dishka(container, app)
    return app

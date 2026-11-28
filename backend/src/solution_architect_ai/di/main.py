import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from solution_architect_ai.application.errors.chat_errors import (
    ChatError,
    Conflict,
    Missing,
    StoredDataCorrupt,
)
from solution_architect_ai.application.errors.clarification_errors import (
    ClarificationConflict,
    PermissionDenied,
)
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.application.models.chat_dto import APIError
from solution_architect_ai.application.protocols.discussion_protocols import DiscussionContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.config.models import Mode
from solution_architect_ai.config.settings import Settings, load_settings
from solution_architect_ai.di.discussions import DiscussionProvider
from solution_architect_ai.di.documents import DocumentProvider
from solution_architect_ai.di.extraction import ExtractionProvider
from solution_architect_ai.di.providers import AppProvider
from solution_architect_ai.presentation.api import create_http_app
from solution_architect_ai.presentation.document_routes import document_error
from solution_architect_ai.presentation.extraction_routes import extraction_error


async def chat_error(_request: Request, error: Exception) -> JSONResponse:
    if isinstance(error, StoredDataCorrupt):
        return JSONResponse(status_code=500, content={"code": "stored_data_corrupt"})
    if isinstance(error, PermissionDenied):
        return JSONResponse(status_code=403, content={"code": "permission_denied"})
    if isinstance(error, ClarificationConflict):
        return JSONResponse(status_code=409, content={"code": error.code})
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
    container: AsyncContainer = make_async_container(
        AppProvider(),
        DocumentProvider(),
        ExtractionProvider(),
        DiscussionProvider(),
        context={Settings: settings},
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        required_tasks: list[asyncio.Task[None]] = []
        _app.state.worker_tasks = required_tasks
        try:
            async with workers(container, required_tasks):
                yield
        finally:
            await container.close()

    app: FastAPI = create_http_app(lifespan=lifespan)
    app.add_exception_handler(ChatError, chat_error)
    app.add_exception_handler(DocumentFailure, document_error)
    app.add_exception_handler(StoredExtractionCorrupt, extraction_error)
    setup_dishka(container, app)
    return app


@asynccontextmanager
async def workers(
    container: AsyncContainer, required_tasks: list[asyncio.Task[None]] | None = None
) -> AsyncGenerator[None]:
    worker: RunWorker = await container.get(RunWorker)
    worker.discussion_context = await container.get(DiscussionContext)
    extraction: ExtractionWorker = await container.get(ExtractionWorker)
    documents: DocumentService = await container.get(DocumentService)
    await worker.recover()
    try:
        await documents.recover_uploads()
    except DocumentFailure as error:
        logging.getLogger(__name__).error("document_recovery_pending code=%s", error.code.value)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        chat_task: asyncio.Task[None] = group.create_task(worker.serve())
        extraction_task: asyncio.Task[None] = group.create_task(extraction.serve())
        if required_tasks is not None:
            required_tasks.extend((chat_task, extraction_task))
        try:
            yield
        finally:
            worker.stopping.set()
            extraction.stopping.set()

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

from solution_architect_ai.application.errors.chat_errors import ChatError, Conflict, Missing
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
from solution_architect_ai.presentation.clarification_routes import router as clarification_router
from solution_architect_ai.presentation.discussion_routes import router as discussion_router
from solution_architect_ai.presentation.document_routes import document_error
from solution_architect_ai.presentation.document_routes import router as document_router
from solution_architect_ai.presentation.extraction_routes import extraction_error
from solution_architect_ai.presentation.extraction_routes import router as extraction_router
from solution_architect_ai.presentation.routes import router


async def chat_error(_request: Request, error: Exception) -> JSONResponse:
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
        try:
            async with workers(container):
                yield
        finally:
            await container.close()

    app: FastAPI = FastAPI(title="SolutionArchitectAI", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(document_router)
    app.include_router(extraction_router)
    app.include_router(clarification_router)
    app.include_router(discussion_router)
    app.add_exception_handler(ChatError, chat_error)
    app.add_exception_handler(DocumentFailure, document_error)
    app.add_exception_handler(StoredExtractionCorrupt, extraction_error)
    setup_dishka(container, app)
    return app


@asynccontextmanager
async def workers(container: AsyncContainer) -> AsyncGenerator[None]:
    worker: RunWorker = await container.get(RunWorker)
    worker.discussions = await container.get(DiscussionContext)
    extraction: ExtractionWorker = await container.get(ExtractionWorker)
    documents: DocumentService = await container.get(DocumentService)
    await worker.recover()
    try:
        await documents.recover_uploads()
    except DocumentFailure as error:
        logging.getLogger(__name__).error("document_recovery_pending code=%s", error.code.value)
    group: asyncio.TaskGroup
    async with asyncio.TaskGroup() as group:
        group.create_task(worker.serve())
        group.create_task(extraction.serve())
        try:
            yield
        finally:
            worker.stopping.set()
            extraction.stopping.set()

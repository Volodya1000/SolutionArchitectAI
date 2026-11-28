from typing import Final

from fastapi import FastAPI
from starlette.types import Lifespan

from solution_architect_ai.presentation.api_models import ApiFailure, ApiValidationFailure
from solution_architect_ai.presentation.clarification_routes import router as clarification_router
from solution_architect_ai.presentation.discussion_routes import router as discussion_router
from solution_architect_ai.presentation.document_routes import router as document_router
from solution_architect_ai.presentation.extraction_routes import router as extraction_router
from solution_architect_ai.presentation.routes import router

_HTTP_ERRORS: Final[dict[int | str, dict[str, object]]] = {
    status: {"model": ApiFailure} for status in (400, 403, 404, 409, 413, 415, 500, 503)
}


def create_http_app(*, lifespan: Lifespan[FastAPI] | None = None) -> FastAPI:
    app: FastAPI = FastAPI(
        title="SolutionArchitectAI",
        version="0.1.0",
        lifespan=lifespan,
        responses={**_HTTP_ERRORS, 422: {"model": ApiFailure | ApiValidationFailure}},
    )
    app.include_router(router)
    app.include_router(document_router)
    app.include_router(extraction_router)
    app.include_router(clarification_router)
    app.include_router(discussion_router)
    return app

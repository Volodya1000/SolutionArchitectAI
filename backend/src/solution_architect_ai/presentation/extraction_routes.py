from typing import Annotated, Literal
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from solution_architect_ai.application.models.extraction_models import (
    AnswerHistorySelection,
    ExtractionHistory,
    ExtractionMatches,
    ExtractionStart,
    ExtractionSummary,
    ExtractionView,
)
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)


async def extraction_error(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"code": "stored_extraction_corrupt"})


@router.post("/extractions", status_code=202)
async def start(
    body: ExtractionStart, service: FromDishka[RequirementsExtractionService]
) -> ExtractionView:
    return await service.start(body)


@router.get("/extractions")
async def list_extractions(
    service: FromDishka[RequirementsExtractionService],
) -> list[ExtractionView]:
    return await service.list_runs()


@router.get("/extractions/history")
async def history(
    service: FromDishka[RequirementsExtractionService],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExtractionHistory:
    return await service.list_history(limit=limit, offset=offset)


@router.get("/extractions/matching")
async def matching(
    service: FromDishka[RequirementsExtractionService],
    version_ids: Annotated[list[UUID], Query(min_length=1, max_length=20)],
    analysis_scope: Annotated[str, Query(max_length=1000)],
    answer_history_mode: Literal["reuse", "new"] = "reuse",
    answer_history_id: UUID | None = None,
) -> ExtractionMatches:
    return await service.get_matching(
        version_ids,
        analysis_scope,
        AnswerHistorySelection(mode=answer_history_mode, history_id=answer_history_id),
    )


@router.get("/extractions/{run_id}/status")
async def get_status(
    run_id: UUID, service: FromDishka[RequirementsExtractionService]
) -> ExtractionSummary:
    return await service.get_status(run_id)


@router.get("/extraction-operations/{operation_id}")
async def get_operation(
    operation_id: UUID, service: FromDishka[RequirementsExtractionService]
) -> ExtractionView:
    return await service.get_operation(operation_id)


@router.get("/extractions/{run_id}")
async def get(run_id: UUID, service: FromDishka[RequirementsExtractionService]) -> ExtractionView:
    return await service.get(run_id)


@router.post("/extractions/{run_id}/cancel")
async def cancel(
    run_id: UUID, service: FromDishka[RequirementsExtractionService]
) -> ExtractionView:
    return await service.cancel(run_id)

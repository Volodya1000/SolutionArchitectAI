from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)

router: APIRouter = APIRouter(prefix="/api/extractions", route_class=DishkaRoute)


async def extraction_error(_request: Request, _error: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"code": "stored_extraction_corrupt"})


@router.post("", status_code=202)
async def start(
    body: ExtractionStart, service: FromDishka[RequirementsExtractionService]
) -> ExtractionView:
    return await service.start(body)


@router.get("")
async def list_extractions(
    service: FromDishka[RequirementsExtractionService],
) -> list[ExtractionView]:
    return await service.list_runs()


@router.get("/{run_id}")
async def get(run_id: UUID, service: FromDishka[RequirementsExtractionService]) -> ExtractionView:
    return await service.get(run_id)


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: UUID, service: FromDishka[RequirementsExtractionService]
) -> ExtractionView:
    return await service.cancel(run_id)

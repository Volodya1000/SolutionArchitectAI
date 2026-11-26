from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from solution_architect_ai.application.extraction import ExtractionService
from solution_architect_ai.application.extraction_models import ExtractionStart, ExtractionView

router: APIRouter = APIRouter(prefix="/api/extractions", route_class=DishkaRoute)


@router.post("", status_code=202)
async def start(body: ExtractionStart, service: FromDishka[ExtractionService]) -> ExtractionView:
    return await service.start(body)


@router.get("")
async def list_extractions(service: FromDishka[ExtractionService]) -> list[ExtractionView]:
    return await service.list_runs()


@router.get("/{run_id}")
async def get(run_id: UUID, service: FromDishka[ExtractionService]) -> ExtractionView:
    return await service.get(run_id)


@router.post("/{run_id}/cancel")
async def cancel(run_id: UUID, service: FromDishka[ExtractionService]) -> ExtractionView:
    return await service.cancel(run_id)

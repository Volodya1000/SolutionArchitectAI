from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationView,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
)
from solution_architect_ai.application.services.clarification_service import ClarificationService

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)


@router.get("/extractions/{run_id}/clarifications")
async def clarifications(
    run_id: UUID, service: FromDishka[ClarificationService]
) -> ClarificationView:
    return await service.get(run_id)


@router.post("/extractions/{run_id}/questions/{question_id}/answers")
async def answer(
    run_id: UUID,
    question_id: UUID,
    body: AnswerClarification,
    service: FromDishka[ClarificationService],
) -> DecisionResult:
    return await service.answer(run_id, question_id, body)


@router.post("/extractions/{run_id}/resume")
async def resume(
    run_id: UUID, body: ResumeRun, service: FromDishka[ClarificationService]
) -> CommandResult:
    return await service.resume(run_id, body)


@router.post("/assumptions/{assumption_id}/resolve")
async def resolve(
    assumption_id: UUID, body: ResolveAssumption, service: FromDishka[ClarificationService]
) -> DecisionResult:
    return await service.resolve(assumption_id, body)


@router.get("/clarification-operations/{operation_id}")
async def operation(
    operation_id: UUID, service: FromDishka[ClarificationService]
) -> DecisionResult | CommandResult:
    return await service.operation(operation_id)

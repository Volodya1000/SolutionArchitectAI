from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from solution_architect_ai.application.models.chat_dto import ChatView
from solution_architect_ai.application.models.discussion_models import (
    CreateDiscussion,
    DiscussionView,
)
from solution_architect_ai.application.services.discussion_service import DiscussionService

router: APIRouter = APIRouter(prefix="/api", route_class=DishkaRoute)


@router.post("/discussions", status_code=201)
async def create(body: CreateDiscussion, service: FromDishka[DiscussionService]) -> ChatView:
    return await service.create(body)


@router.get("/chats/{chat_id}/discussion")
async def subject(chat_id: UUID, service: FromDishka[DiscussionService]) -> DiscussionView | None:
    return await service.get(chat_id)


@router.get("/discussion-operations/{operation_id}")
async def operation(operation_id: UUID, service: FromDishka[DiscussionService]) -> ChatView:
    return await service.operation(operation_id)

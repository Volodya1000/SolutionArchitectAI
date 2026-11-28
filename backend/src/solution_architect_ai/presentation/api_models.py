from pydantic import BaseModel, JsonValue

from solution_architect_ai.application.models.chat_dto import DTO


class ApiFailure(DTO):
    code: str


class ApiValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str
    input: JsonValue = None
    ctx: dict[str, JsonValue] | None = None


class ApiValidationFailure(DTO):
    detail: list[ApiValidationIssue]

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from solution_architect_ai.application.context.context_models import ContextPart
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from solution_architect_ai.application.models.structured_models import ModelProfile
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)


@dataclass(frozen=True)
class AgentRequest:
    task_id: UUID
    run_id: UUID
    operation_id: UUID
    attempt_id: UUID
    part: ContextPart
    profile: ModelProfile
    contract_version: str = CONTRACT_VERSION
    prompt_version: str = PROMPT_VERSION
    role: Literal["requirements_extraction"] = "requirements_extraction"


@dataclass(frozen=True)
class AgentResult:
    run_id: UUID
    attempt_id: UUID
    payload: RequirementsExtraction
    contract_version: str = CONTRACT_VERSION
    role: Literal["requirements_extraction"] = "requirements_extraction"

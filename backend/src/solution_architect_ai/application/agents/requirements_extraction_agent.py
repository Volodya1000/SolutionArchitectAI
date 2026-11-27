from dataclasses import dataclass
from functools import partial
from typing import Literal
from uuid import UUID

from solution_architect_ai.application.agents.extraction_result_mapper import (
    validate_context_language,
)
from solution_architect_ai.application.context.context_models import ContextPart
from solution_architect_ai.application.models.extraction_models import (
    RequirementsExtraction,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredRequest,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION,
    PROMPT_VERSION,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
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


class RequirementsExtractionAgent:
    def __init__(self, generator: StructuredOutputGenerator) -> None:
        self.generator: StructuredOutputGenerator = generator

    async def extract(self, request: AgentRequest, budget: ExecutionBudget) -> AgentResult:
        result: RequirementsExtraction = await self.generator.generate(
            StructuredRequest(request.part.messages, request.profile),
            RequirementsExtraction,
            budget,
            validator=partial(validate_context_language, part=request.part),
        )
        return AgentResult(request.run_id, request.attempt_id, result)

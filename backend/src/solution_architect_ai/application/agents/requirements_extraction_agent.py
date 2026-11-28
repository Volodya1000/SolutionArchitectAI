from functools import partial

from solution_architect_ai.application.agents.extraction_result_mapper import (
    validate_context_language,
)
from solution_architect_ai.application.models.extraction_agent_models import (
    AgentRequest,
    AgentResult,
)
from solution_architect_ai.application.models.extraction_models import (
    RequirementsExtraction,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    StructuredRequest,
)
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)


class RequirementsExtractionAgent:
    def __init__(self, structured_output_generator: StructuredOutputGenerator) -> None:
        self.structured_output_generator: StructuredOutputGenerator = structured_output_generator

    async def extract(self, request: AgentRequest, budget: ExecutionBudget) -> AgentResult:
        result: RequirementsExtraction = await self.structured_output_generator.generate(
            StructuredRequest(request.part.messages, request.profile),
            RequirementsExtraction,
            budget,
            validator=partial(validate_context_language, part=request.part),
        )
        return AgentResult(request.run_id, request.attempt_id, result)

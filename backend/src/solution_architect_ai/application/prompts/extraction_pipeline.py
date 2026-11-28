from typing import Final

from solution_architect_ai.application.models.extraction_pipeline_models import (
    ExtractionPipelineVersions,
)
from solution_architect_ai.application.prompts.clarification_prompt import (
    CONTRACT_VERSION as CLARIFICATION_CONTRACT_VERSION,
)
from solution_architect_ai.application.prompts.clarification_prompt import (
    PROMPT_VERSION as CLARIFICATION_PROMPT_VERSION,
)
from solution_architect_ai.application.prompts.clarification_review_prompt import (
    PROMPT_VERSION as CLARIFICATION_REVIEW_PROMPT_VERSION,
)
from solution_architect_ai.application.prompts.conflict_assessment_prompt import (
    CONFLICT_ASSESSMENT_PROMPT_VERSION,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    CONTRACT_VERSION as EXTRACTION_CONTRACT_VERSION,
)
from solution_architect_ai.application.prompts.extraction_prompt import (
    PROMPT_VERSION as EXTRACTION_PROMPT_VERSION,
)
from solution_architect_ai.application.prompts.structured_prompt import (
    PROMPT_VERSION as STRUCTURED_PROMPT_VERSION,
)

EXTRACTION_CONTEXT_CONTRACT_VERSION: Final[str] = "source-aliases-1"


def current_extraction_pipeline_versions() -> ExtractionPipelineVersions:
    return ExtractionPipelineVersions(
        extraction_prompt_version=EXTRACTION_PROMPT_VERSION,
        extraction_contract_version=EXTRACTION_CONTRACT_VERSION,
        clarification_prompt_version=CLARIFICATION_PROMPT_VERSION,
        clarification_contract_version=CLARIFICATION_CONTRACT_VERSION,
        clarification_review_prompt_version=CLARIFICATION_REVIEW_PROMPT_VERSION,
        conflict_assessment_prompt_version=CONFLICT_ASSESSMENT_PROMPT_VERSION,
        structured_prompt_version=STRUCTURED_PROMPT_VERSION,
        extraction_context_contract_version=EXTRACTION_CONTEXT_CONTRACT_VERSION,
    )

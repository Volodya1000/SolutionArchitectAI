from solution_architect_ai.application.models.chat_dto import DTO


class ExtractionPipelineVersions(DTO):
    extraction_prompt_version: str | None = None
    extraction_contract_version: str | None = None
    clarification_prompt_version: str | None = None
    clarification_contract_version: str | None = None
    clarification_review_prompt_version: str | None = None
    conflict_assessment_prompt_version: str | None = None
    structured_prompt_version: str | None = None
    extraction_context_contract_version: str | None = None

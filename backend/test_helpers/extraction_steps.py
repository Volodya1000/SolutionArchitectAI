from solution_architect_ai.application.models.extraction_policy import ExtractionPolicy
from solution_architect_ai.application.workflows.extraction_budget_builder import (
    ExtractionBudgetBuilder,
)
from solution_architect_ai.application.workflows.extraction_context_assembler import (
    ExtractionContextAssembler,
)
from solution_architect_ai.application.workflows.extraction_finalizer import ExtractionFinalizer
from solution_architect_ai.application.workflows.extraction_part_extractor import (
    ExtractionPartExtractor,
)
from solution_architect_ai.application.workflows.extraction_steps import ExtractionSteps


def configured_extraction_steps(
    original: ExtractionSteps, policy: ExtractionPolicy
) -> ExtractionSteps:
    assembler: ExtractionContextAssembler = ExtractionContextAssembler(
        original.extraction_store_context,
        original.documents_service,
        original.extraction_context_builder,
        policy,
    )
    budget_builder: ExtractionBudgetBuilder = ExtractionBudgetBuilder(
        original.extraction_store_context, policy
    )
    part_extractor: ExtractionPartExtractor = ExtractionPartExtractor(
        original.extraction_store_context,
        assembler,
        original.requirements_extraction_agent,
        policy,
        budget_builder,
    )
    return ExtractionSteps(
        assembler, part_extractor, ExtractionFinalizer(original.extraction_store_context, assembler)
    )

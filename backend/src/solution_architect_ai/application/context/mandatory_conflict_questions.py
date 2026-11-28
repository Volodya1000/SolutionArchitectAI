from uuid import UUID, uuid4

from solution_architect_ai.application.context.clarification_question_merge import merge_sources
from solution_architect_ai.application.context.source_fingerprints import requirement_fingerprint
from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import RequirementView


def uncovered_conflicts(
    assessments: list[ConflictAssessment], questions: list[ClarificationQuestion]
) -> list[ConflictAssessment]:

    covered: set[UUID] = {
        identifier
        for question in questions
        if question.mandatory_conflict is not None
        for identifier in question.requirement_ids
    }

    return [
        item
        for item in assessments
        if item.status == "confirmed" and item.requirement_id not in covered
    ]


def mandatory_conflict_question(
    requirement: RequirementView, assessment: ConflictAssessment
) -> ClarificationQuestion:

    return ClarificationQuestion(
        id=uuid4(),
        gap_key=f"mandatory-conflict:{requirement_fingerprint(requirement)}",
        text="Как устранить противоречие обязательному правилу?",
        basis=assessment.reason,
        dependent_decision="Результат, зависящий от обязательного правила",
        blocking=True,
        requirement_ids=[requirement.id],
        sources=assessment.sources or requirement.sources,
        mandatory_conflict=assessment.reason,
    )


def bind_confirmed_conflicts(
    requirements: list[RequirementView],
    questions: list[ClarificationQuestion],
    assessments: list[ConflictAssessment],
) -> list[ClarificationQuestion]:

    result: list[ClarificationQuestion] = [item.model_copy(deep=True) for item in questions]

    assessment: ConflictAssessment

    for assessment in uncovered_conflicts(assessments, result):
        requirement: RequirementView = next(
            item for item in requirements if item.id == assessment.requirement_id
        )

        question: ClarificationQuestion | None = next(
            (
                item
                for item in result
                if item.status == "open" and requirement.id in item.requirement_ids
            ),
            None,
        )

        if question is None:
            result.append(mandatory_conflict_question(requirement, assessment))

        else:
            question.mandatory_conflict = assessment.reason

            question.blocking = True

            question.sources = merge_sources([*question.sources, *assessment.sources])

    return result

from uuid import UUID

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.models.clarification_models import (
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
)
from solution_architect_ai.application.models.discussion_models import DiscussionBinding
from solution_architect_ai.application.models.extraction_models import RequirementView


def select_discussion_scope(
    binding: DiscussionBinding, state: ClarificationView
) -> ClarificationView:
    if state.history_id != binding.view.history_id:
        raise Missing("discussion_history_changed")
    selected_sources: set[tuple[UUID | None, str]] = {
        (source.version_id, source.fragment_id) for source in binding.sources
    }
    requirements: list[RequirementView] = (
        [
            requirement
            for requirement in state.requirements
            if requirement.id == binding.view.requirement_id
        ]
        if binding.view.requirement_id is not None
        else [
            requirement
            for requirement in state.requirements
            if any(
                (source.version_id, source.fragment_id) in selected_sources
                for source in requirement.sources
            )
        ]
    )
    if binding.view.requirement_id is not None and not requirements:
        raise Missing("discussion_requirement")
    requirement_ids: set[UUID] = {requirement.id for requirement in requirements}
    questions: list[ClarificationQuestion] = [
        question
        for question in state.questions
        if requirement_ids.intersection(question.requirement_ids)
    ]
    question_ids: set[UUID] = {question.id for question in questions}
    decisions: list[DecisionResult] = [
        decision for decision in state.decisions if decision.question_id in question_ids
    ]
    decision_ids: set[UUID] = {decision.decision_id for decision in decisions}
    return ClarificationView(
        run_id=state.run_id,
        history_id=state.history_id,
        cycle=state.cycle,
        initialized=state.initialized,
        resume_pending=state.resume_pending,
        resume_version=state.resume_version,
        metadata=state.metadata,
        requirements=requirements,
        questions=questions,
        decisions=decisions,
        risks=[risk for risk in state.risks if risk.decision_id in decision_ids],
    )

from solution_architect_ai.application.models.clarification_models import ClarificationQuestion
from solution_architect_ai.application.models.extraction_models import SourceRef


def merge_question_windows(questions: list[ClarificationQuestion]) -> ClarificationQuestion:
    ordered: list[ClarificationQuestion] = sorted(
        questions, key=lambda question: (-question.revision, str(question.id))
    )
    merged: ClarificationQuestion = ordered[0].model_copy(deep=True)
    current: list[ClarificationQuestion] = [
        question for question in ordered if question.revision == merged.revision
    ]
    merged.status = (
        "open"
        if any(question.status == "open" for question in current)
        else "answered"
        if any(question.status == "answered" for question in current)
        else "assumed"
    )
    merged.requirement_ids = sorted(
        {identifier for question in ordered for identifier in question.requirement_ids}, key=str
    )
    merged.blocking = any(question.blocking for question in ordered)
    merged.sources = merge_sources([source for question in ordered for source in question.sources])
    merged.previous_sources = merge_sources(
        [source for question in ordered for source in question.previous_sources]
    )
    merged.text = merge_reasons([question.text for question in ordered])
    merged.basis = merge_reasons([question.basis for question in ordered])
    merged.dependent_decision = merge_reasons([question.dependent_decision for question in ordered])
    merged.mandatory_conflict = (
        merge_reasons(
            [question.mandatory_conflict for question in ordered if question.mandatory_conflict]
        )
        or None
    )
    merged.previous_basis = (
        merge_reasons([question.previous_basis for question in ordered if question.previous_basis])
        or None
    )
    merged.source_fingerprints = {
        key: value
        for question in reversed(ordered)
        for key, value in question.source_fingerprints.items()
    }
    merged.requirement_fingerprints = {
        key: value
        for question in reversed(ordered)
        for key, value in question.requirement_fingerprints.items()
    }
    merged.requirement_basis_fingerprints = {
        key: value
        for question in reversed(ordered)
        for key, value in question.requirement_basis_fingerprints.items()
    }
    return merged


def merge_reasons(reasons: list[str]) -> str:
    return "\n".join(sorted({line for reason in reasons for line in reason.splitlines()}))


def merge_sources(sources: list[SourceRef]) -> list[SourceRef]:
    unique: dict[str, SourceRef] = {source.model_dump_json(): source for source in sources}
    return [unique[key] for key in sorted(unique)]

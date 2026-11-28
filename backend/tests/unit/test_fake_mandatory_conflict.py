import json
from typing import Final

from solution_architect_ai.application.models.clarification_agent_models import ClarificationSet
from solution_architect_ai.application.models.conflict_assessment_models import (
    ConflictAssessmentVerdict,
)
from solution_architect_ai.application.models.extraction_models import RequirementsExtraction
from tools.fake_llm.server import structured_answer

SOURCE_FRAGMENTS: Final[list[dict[str, str]]] = [
    {"fragment_id": "f0", "text": "# Контроль [clarification:mandatory-conflict]"},
    {"fragment_id": "f1", "text": "Обязательное правило: хранить записи не менее 30 дней."},
    {"fragment_id": "f2", "text": "Требование: удалять записи через 7 дней."},
]


def request_body(role: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": role,
        "fragments": SOURCE_FRAGMENTS,
        "requirements": [{"id": "r0", "fragment_ids": ["f1", "f2"]}],
    }
    return {"messages": [{"role": "user", "content": json.dumps(payload)}]}


def test_controlled_mandatory_conflict_extracts_candidate_with_two_authentic_statements() -> None:
    result: RequirementsExtraction = RequirementsExtraction.model_validate_json(
        structured_answer(request_body("extraction"))
    )
    assert len(result.contradictions) == 1
    assert len({item.quote for item in result.contradictions[0].evidence}) == 2
    assert result.requirements == []
    assert {item.quote for item in result.contradictions[0].evidence} == {
        item["text"] for item in SOURCE_FRAGMENTS[1:]
    }


def test_independent_conflict_assessment_confirms_even_when_question_model_returns_empty() -> None:
    questions: ClarificationSet = ClarificationSet.model_validate_json(
        structured_answer(request_body("clarification"))
    )
    assert questions.questions == []
    payload: object = json.loads(structured_answer(request_body("conflict_assessment")))
    assert isinstance(payload, dict)
    assert payload.get("status") == "confirmed"
    verdict: ConflictAssessmentVerdict = ConflictAssessmentVerdict.model_validate(payload)
    assert len({item.quote for item in verdict.evidence}) == 2
    assert {item.quote for item in verdict.evidence} == {
        item["text"] for item in SOURCE_FRAGMENTS[1:]
    }

from typing import Final
from uuid import UUID, uuid4

import pytest

from backend.test_helpers.extraction_resources import ExtractionResources
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    SourceVersion,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.application.models.structured_models import ExecutionBudget

DOCUMENT: Final[str] = "\n\n".join(
    ("# Условия", "Первое условие нуждается в уточнении.", "Второе условие нуждается в уточнении.")
)


async def install_questions(
    resources: ExtractionResources,
    monkeypatch: pytest.MonkeyPatch,
    count: int = 2,
    *,
    blocking: bool = True,
) -> None:
    agent: ClarificationAgent = await resources.container.get(ClarificationAgent)

    async def scripted(
        context: ClarificationContext, _budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        return [
            ClarificationQuestion(
                id=uuid4(),
                gap_key=f"condition:{index}",
                text="Какое поведение требуется?",
                basis="Не задано условие",
                dependent_decision=f"Решение {index}",
                blocking=blocking,
                requirement_ids=[UUID(identifier)],
                sources=[],
            )
            for index, identifier in enumerate(
                str(requirement.id)
                for requirement in sorted(context.requirements, key=lambda item: item.original_text)
                if str(requirement.id) in context.requirement_ids
            )
            if index < count
        ]

    monkeypatch.setattr(agent, "clarify", scripted)


def answer(question: ClarificationQuestion, *, assumption: bool = False) -> AnswerClarification:
    return AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=question.revision,
        source_versions=list(
            {
                source.version_id: SourceVersion(version_id=source.version_id, sha256=source.sha256)
                for source in question.sources
                if source.version_id and source.sha256
            }.values()
        ),
        kind="assumption" if assumption else "answer",
        text="Сохранить условие архитектора",
        basis="Решение архитектора",
        assumption=AssumptionDetails(
            responsible="Архитектор",
            verification_condition="До реализации",
            consequences="Неверная обработка",
            mitigation="Проверка заказчиком",
        )
        if assumption
        else None,
    )


async def start_fresh(resources: ExtractionResources, version_id: UUID) -> ExtractionView:
    run: ExtractionView = await resources.service.start(
        ExtractionStart(operation_id=uuid4(), version_ids=[version_id], answer_history_mode="new")
    )
    resources.runs.append(run.id)
    return run

import json
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from backend.test_helpers.clarification_models import ClarificationModel
from backend.test_helpers.sql_store_setup import SqlStoreSetup
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContextBuilder,
)
from solution_architect_ai.application.models.clarification_context_models import (
    ClarificationContext,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    DecisionResult,
    SourceVersion,
)
from solution_architect_ai.application.models.conflict_assessment_models import ConflictAssessment
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    RequirementView,
    StoredModelProfile,
)
from solution_architect_ai.application.models.structured_models import (
    ExecutionBudget,
    ModelProfile,
    StructuredMode,
)
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.structured_output_generator import (
    StructuredOutputGenerator,
)
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.domain.documents import (
    ParsedDocument,
)
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow


async def seed_analysis(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    source: ParsedDocument,
    requirement: RequirementView,
    history_id: UUID | None = None,
) -> UUID:
    run_id: UUID = uuid4()
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(),
        version_ids=[source.version_id],
        answer_history_mode="new" if history_id is None else "reuse",
        answer_history_id=history_id,
    )
    profile: StoredModelProfile = StoredModelProfile.model_validate(
        LLMSettings().model_dump(exclude={"api_key"})
    )
    snapshot: ExtractionView = ExtractionView(
        id=run_id,
        status=RunStatus.WAITING_INPUT,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model="fake-chat",
        model_profile=profile,
        coverage=CoverageView(),
        contract_version="test",
        prompt_version="test",
        requirements=[requirement],
        version_ids=[source.version_id],
    )
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        store.session.add(
            ExtractionRow(
                id=run_id,
                task_id=stores.actor.task_id,
                operation_id=command.operation_id,
                payload_digest="test",
                config_digest="test",
                command_json=command.model_dump_json(),
                snapshot_json=snapshot.model_dump_json(),
                status=snapshot.status.value,
                created_at=snapshot.created_at,
            )
        )
    return run_id


async def prepare_questions(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    run_id: UUID,
    source: ParsedDocument,
    requirement: RequirementView,
    *,
    candidate: bool = True,
    changed_basis: bool | None = False,
) -> None:
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        history: list[ClarificationQuestion] = await store.history(run_id)
        decisions: list[DecisionResult] = await store.history_decisions(run_id)
    context: ClarificationContext = ClarificationContextBuilder().build(
        (source,),
        [requirement],
        history,
        decisions,
        ModelProfile("test", StructuredMode.JSON_TEXT, 64000, 4096),
    )
    payload: dict[str, object] = {
        "questions": [
            {
                "gap_key": history[0].gap_key if history else "reports:failure",
                "text": "Как обрабатывать отказ?",
                "basis": "Условие изменилось" if changed_basis else "Нет условия",
                "dependent_decision": "Обработка отказа",
                "blocking": True,
                "requirement_ids": ["r0"],
                "evidence": [{"fragment_id": "f0", "quote": requirement.sources[0].quote}],
                **({"changed_basis": changed_basis} if changed_basis is not None else {}),
            }
        ]
        if candidate
        else []
    }
    generator: StructuredOutputGenerator = StructuredOutputGenerator(
        ClarificationModel(json.dumps(payload)),
        GenerationPolicy(1, 10, 0, 1, 0, 60000),
        LangChainTokenCounter(2, chat_prompt=False),
    )
    questions: list[ClarificationQuestion] = await ClarificationAgent(generator).clarify(
        context,
        ExecutionBudget(1, monotonic() + 10, 5, correction_retries=0),
    )
    async with stores.open() as store:
        await store.save_questions(run_id, questions)


def answer_command(
    question: ClarificationQuestion, text: str = "Повторить запрос"
) -> AnswerClarification:
    return AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=question.revision,
        source_versions=[
            SourceVersion(version_id=source.version_id, sha256=source.sha256)
            for source in question.sources
            if source.version_id and source.sha256
        ],
        kind="answer",
        text=text,
        basis="Решение архитектора",
    )


async def establish_conflict(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore], run_id: UUID, requirement: RequirementView
) -> None:
    store: SqlAlchemyClarificationStore
    async with stores.open() as store:
        await store.save_conflict_assessments(
            run_id,
            [
                ConflictAssessment(
                    requirement_id=requirement.id,
                    status="confirmed",
                    reason=requirement.normalized_text,
                    sources=requirement.sources,
                )
            ],
        )

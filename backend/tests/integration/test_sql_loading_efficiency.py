import json
import os
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event
from sqlalchemy.engine.interfaces import DBAPICursor
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from solution_architect_ai.application.errors.chat_errors import Missing
from solution_architect_ai.application.errors.extraction_errors import StoredExtractionCorrupt
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    RiskView,
)
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    PartResult,
    RequirementView,
    StoredModelProfile,
)
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.di.providers import database_url
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    DecisionRow,
    QuestionRevisionRow,
    RiskRow,
)
from solution_architect_ai.persistence.clarifications.clarification_queries import (
    ClarificationQueries,
)
from solution_architect_ai.persistence.extractions.extraction_models import (
    ExtractionPartRow,
    ExtractionRow,
)
from solution_architect_ai.persistence.extractions.extraction_store import SqlAlchemyExtractionStore
from solution_architect_ai.persistence.models import ProjectRow, TaskRow

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]
PROFILE: Final[StoredModelProfile] = StoredModelProfile.model_validate(
    LLMSettings().model_dump(mode="json", exclude={"api_key"})
)


@pytest.fixture(name="sql_session")
async def sql_session_fixture() -> AsyncGenerator[AsyncSession]:
    assert os.environ.get("SAA_DATABASE__DATABASE", "").endswith("_test")
    engine: AsyncEngine = create_async_engine(database_url(bootstrap()))
    try:
        connection: AsyncConnection
        async with engine.connect() as connection, connection.begin():
            session: AsyncSession
            async with AsyncSession(connection, expire_on_commit=False) as session:
                yield session
            await connection.rollback()
    finally:
        await engine.dispose()


@dataclass
class SqlMetrics:
    statements: list[str] = field(default_factory=list)
    selected_records: int = 0

    @property
    def bulk_part_payload_queries(self) -> int:
        return sum(
            statement.startswith("SELECT")
            and "requirements_extraction_parts.result_json" in statement
            and "requirements_extraction_parts.part_id =" not in statement
            and "jsonb_array_elements" not in statement
            for statement in self.statements
        )

    def record(self, name: str) -> None:
        destination: str | None = os.environ.get("CODEX_SQL_EVIDENCE")
        if destination is None:
            return
        path: Path = Path(destination)
        results: dict[str, object] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        results[name] = {
            "queries": len(self.statements),
            "selected_records": self.selected_records,
            "bulk_part_payload_queries": self.bulk_part_payload_queries,
        }
        path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


@contextmanager
def capture_sql(connection: AsyncConnection) -> Iterator[SqlMetrics]:
    metrics: SqlMetrics = SqlMetrics()

    def after_query(
        _connection: object,
        cursor: DBAPICursor,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        metrics.statements.append(statement)
        if statement.startswith("SELECT"):
            metrics.selected_records += max(0, cursor.rowcount)

    event.listen(connection.sync_connection, "after_cursor_execute", after_query)
    try:
        yield metrics
    finally:
        event.remove(connection.sync_connection, "after_cursor_execute", after_query)


async def seed_extraction(session: AsyncSession) -> tuple[ExtractionRow, RequirementView]:
    project_id: UUID = uuid4()
    task_id: UUID = uuid4()
    session.add(ProjectRow(id=project_id, title="SQL loading test"))
    await session.flush()
    session.add(TaskRow(id=task_id, project_id=project_id, title="SQL loading test"))
    await session.flush()
    requirement: RequirementView = RequirementView(
        id=uuid4(),
        category=RequirementCategory.FUNCTIONAL,
        original_text="Keep records",
        normalized_text="Keep records",
        sources=[],
    )
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[uuid4()], answer_history_mode="new"
    )
    view: ExtractionView = ExtractionView(
        id=uuid4(),
        status=RunStatus.RUNNING,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model=PROFILE.model,
        model_profile=PROFILE,
        version_ids=command.version_ids,
        coverage=CoverageView(),
        requirements=[requirement],
        contract_version="test",
        prompt_version="test",
    )
    row: ExtractionRow = ExtractionRow(
        id=view.id,
        task_id=task_id,
        operation_id=command.operation_id,
        payload_digest="test",
        config_digest="test",
        command_json=command.model_dump_json(),
        snapshot_json=view.model_dump_json(),
        status=view.status.value,
    )
    session.add(row)
    await session.flush()
    return row, requirement


async def seed_parts(session: AsyncSession, run_id: UUID, count: int) -> None:
    index: int
    for index in range(count):
        requirement: RequirementView = RequirementView(
            id=uuid4(),
            category=RequirementCategory.FUNCTIONAL,
            original_text="Keep " * 2000,
            normalized_text="Keep " * 2000,
            sources=[],
        )
        part: PartResult = PartResult(
            part_id=f"part-{index}",
            requirements=[requirement],
            fragment_ids=["shared", str(index)],
        )
        session.add(
            ExtractionPartRow(
                id=uuid4(),
                run_id=run_id,
                part_id=part.part_id,
                result_json=part.model_dump_json(),
            )
        )
    await session.flush()


async def test_part_progress_avoids_loading_prior_results(sql_session: AsyncSession) -> None:
    run: ExtractionRow
    _requirement: RequirementView
    run, _requirement = await seed_extraction(sql_session)
    await seed_parts(sql_session, run.id, 10)
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(sql_session, task_id=run.task_id)
    part: PartResult = PartResult(part_id="new", requirements=[], fragment_ids=["shared", "new"])
    metrics: SqlMetrics
    with capture_sql(await sql_session.connection()) as metrics:
        await store.save_part(run.id, part)
    view: ExtractionView = await store.get(run.id)
    metrics.record("save_after_10_parts")
    assert view.progress.completed_parts == 11
    assert view.coverage.processed_fragments == 12
    assert metrics.bulk_part_payload_queries == 0
    assert metrics.selected_records <= 3


async def test_part_replay_keeps_exact_unique_fragment_count(sql_session: AsyncSession) -> None:
    run: ExtractionRow
    _requirement: RequirementView
    run, _requirement = await seed_extraction(sql_session)
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(sql_session, task_id=run.task_id)
    await store.save_part(
        run.id, PartResult(part_id="first", requirements=[], fragment_ids=["shared", "a"])
    )
    await store.save_part(
        run.id, PartResult(part_id="second", requirements=[], fragment_ids=["shared", "b"])
    )
    metrics: SqlMetrics
    with capture_sql(await sql_session.connection()) as metrics:
        await store.save_part(
            run.id, PartResult(part_id="first", requirements=[], fragment_ids=["fake"])
        )
    view: ExtractionView = await store.get(run.id)
    metrics.record("replay_after_2_parts")
    assert view.progress.completed_parts == 2
    assert view.coverage.processed_fragments == 3
    assert metrics.bulk_part_payload_queries == 0


async def test_part_lookup_reads_only_requested_result_and_validates_it(
    sql_session: AsyncSession,
) -> None:
    run: ExtractionRow
    _requirement: RequirementView
    run, _requirement = await seed_extraction(sql_session)
    await seed_parts(sql_session, run.id, 10)
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(sql_session, task_id=run.task_id)
    legacy_metrics: SqlMetrics
    with capture_sql(await sql_session.connection()) as legacy_metrics:
        legacy_parts: list[PartResult] = await store.parts(run.id)
    legacy_metrics.record("legacy_lookup_all_10_parts")
    metrics: SqlMetrics
    with capture_sql(await sql_session.connection()) as metrics:
        part: PartResult | None = await store.get_part(run.id, "part-7")
    metrics.record("lookup_after_10_parts")
    assert part is not None
    assert part.part_id == "part-7"
    assert metrics.bulk_part_payload_queries == 0
    assert metrics.selected_records <= 2
    assert part == next(result for result in legacy_parts if result.part_id == "part-7")
    assert metrics.selected_records < legacy_metrics.selected_records
    broken: ExtractionPartRow = ExtractionPartRow(
        id=uuid4(), run_id=run.id, part_id="broken", result_json="{"
    )
    sql_session.add(broken)
    await sql_session.flush()
    with pytest.raises(StoredExtractionCorrupt):
        await store.get_part(run.id, "broken")
    foreign_store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(
        sql_session, task_id=uuid4()
    )
    with pytest.raises(Missing):
        await foreign_store.get_part(run.id, "part-7")


@pytest.mark.parametrize("fragment_ids", [None, {}, [1], [None]])
async def test_progress_rejects_malformed_stored_fragment_identifiers(
    sql_session: AsyncSession,
    fragment_ids: object,
) -> None:
    run: ExtractionRow
    _requirement: RequirementView
    run, _requirement = await seed_extraction(sql_session)
    sql_session.add(
        ExtractionPartRow(
            id=uuid4(),
            run_id=run.id,
            part_id="corrupt",
            result_json=json.dumps(
                {"part_id": "corrupt", "requirements": [], "fragment_ids": fragment_ids}
            ),
        )
    )
    await sql_session.flush()
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(sql_session, task_id=run.task_id)
    with pytest.raises(StoredExtractionCorrupt):
        await store.save_part(
            run.id, PartResult(part_id="next", requirements=[], fragment_ids=["a"])
        )
    view: ExtractionView = await store.get(run.id)
    assert not view.coverage.complete
    assert view.progress.completed_parts == 0


@pytest.mark.parametrize("fragment_groups", [[[], []], [["a", "a"], ["a", "b"]]])
async def test_progress_counts_empty_parts_and_duplicate_ids_exactly(
    sql_session: AsyncSession,
    fragment_groups: list[list[str]],
) -> None:
    run: ExtractionRow
    _requirement: RequirementView
    run, _requirement = await seed_extraction(sql_session)
    store: SqlAlchemyExtractionStore = SqlAlchemyExtractionStore(sql_session, task_id=run.task_id)
    index: int
    identifiers: list[str]
    for index, identifiers in enumerate(fragment_groups):
        await store.save_part(
            run.id, PartResult(part_id=str(index), requirements=[], fragment_ids=identifiers)
        )
    view: ExtractionView = await store.get(run.id)
    assert view.progress.completed_parts == 2
    assert view.coverage.processed_fragments == len(
        {identifier for group in fragment_groups for identifier in group}
    )


async def add_decision(
    session: AsyncSession,
    run: ExtractionRow,
    question: ClarificationQuestion,
    revision: int = 1,
) -> None:
    decision: DecisionResult = DecisionResult(
        operation_id=uuid4(),
        run_id=run.id,
        question_id=question.id,
        question_revision=revision,
        decision_id=uuid4(),
        kind="answer",
        text=f"Answer {question.gap_key}",
        basis="Basis",
        author_id=uuid4(),
        author="Architect",
        created_at=datetime.now(UTC),
        requirement_ids=question.requirement_ids,
    )
    risk: RiskView = RiskView(
        id=uuid4(), decision_id=decision.decision_id, consequences="Delay", mitigation="Review"
    )
    session.add(
        DecisionRow(
            id=decision.decision_id,
            question_id=question.id,
            question_revision=revision,
            run_id=run.id,
            snapshot_json=decision.model_dump_json(),
        )
    )
    await session.flush()
    session.add(
        RiskRow(id=risk.id, decision_id=decision.decision_id, snapshot_json=risk.model_dump_json())
    )
    await session.flush()


@pytest.mark.parametrize("question_count", [0, 1, 20])
async def test_clarification_read_batches_questions_decisions_and_risks(
    sql_session: AsyncSession,
    question_count: int,
) -> None:
    run: ExtractionRow
    requirement: RequirementView
    run, requirement = await seed_extraction(sql_session)
    queries: ClarificationQueries = ClarificationQueries(
        sql_session, ActorContext.local(run.task_id)
    )
    questions: list[ClarificationQuestion] = [
        ClarificationQuestion(
            id=uuid4(),
            gap_key=f"gap-{index}",
            text="How long?",
            basis="Not specified",
            dependent_decision="Retention",
            blocking=True,
            requirement_ids=[requirement.id],
            sources=[],
        )
        for index in range(question_count)
    ]
    await queries.save_questions(run.id, questions)
    question: ClarificationQuestion
    for question in questions:
        await add_decision(sql_session, run, question)
    run_id: UUID = run.id
    sql_session.expire_all()
    metrics: SqlMetrics
    with capture_sql(await sql_session.connection()) as metrics:
        view: ClarificationView = await queries.get(run_id)
    metrics.record(f"clarification_{question_count}_questions")
    assert len(view.questions) == len(view.decisions) == len(view.risks) == question_count
    assert {question.id for question in view.questions} == {question.id for question in questions}
    assert all(
        f"Answer gap-{index}" in view.requirements[0].normalized_text
        for index in range(question_count)
    )
    assert len(metrics.statements) <= 8
    if question_count == 0:
        assert len(metrics.statements) == 4


@pytest.mark.parametrize("missing_revision", [False, True])
async def test_batched_read_preserves_linked_revision_boundaries(
    sql_session: AsyncSession,
    missing_revision: bool,
) -> None:
    run: ExtractionRow
    requirement: RequirementView
    run, requirement = await seed_extraction(sql_session)
    queries: ClarificationQueries = ClarificationQueries(
        sql_session, ActorContext.local(run.task_id)
    )
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key="revision-boundary",
        text="How long?",
        basis="Not specified",
        dependent_decision="Retention",
        blocking=True,
        requirement_ids=[requirement.id],
        sources=[],
    )
    await queries.save_questions(run.id, [question])
    await add_decision(sql_session, run, question, 1)
    await add_decision(sql_session, run, question, 2)
    if missing_revision:
        await sql_session.execute(
            delete(QuestionRevisionRow).where(QuestionRevisionRow.question_id == question.id)
        )
        with pytest.raises(Missing):
            await queries.get(run.id)
        return
    view: ClarificationView = await queries.get(run.id)
    assert len(view.questions) == len(view.decisions) == len(view.risks) == 1
    assert view.questions[0].revision == view.decisions[0].question_revision == 1
    assert view.risks[0].decision_id == view.decisions[0].decision_id

import asyncio
from dataclasses import replace
from typing import Final
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from backend.test_helpers.clarification_commands import seed_run, wait_for_database_lock
from backend.test_helpers.sql_store_setup import SqlStoreSetup, clarification_store_setup
from solution_architect_ai.application.errors.chat_errors import Conflict, Missing
from solution_architect_ai.application.errors.clarification_errors import PermissionDenied
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    ResolveAssumption,
    SourceVersion,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
    DecisionRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def submit_contending_command(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    run_id: UUID,
    question_id: UUID,
    command: AnswerClarification,
    attempted: asyncio.Future[int],
) -> DecisionResult | Conflict:
    store: SqlAlchemyClarificationStore
    try:
        async with stores.open() as store:
            backend_pid: int | None = await store.session.scalar(select(func.pg_backend_pid()))
            assert backend_pid is not None
            attempted.set_result(backend_pid)
            return await store.answer(run_id, question_id, command)
    except Conflict as error:
        return error


async def staged_command_race(
    stores: SqlStoreSetup[SqlAlchemyClarificationStore],
    run_id: UUID,
    question_id: UUID,
    commands: list[AnswerClarification],
) -> list[DecisionResult | BaseException]:
    attempted: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    contender: asyncio.Task[DecisionResult | Conflict] | None = None
    winner_store: SqlAlchemyClarificationStore
    try:
        async with stores.open() as winner_store:
            # Match the production lock order, then keep the question locked until the
            # other live command is observably waiting in PostgreSQL.
            await winner_store.run(run_id, lock=True)
            await winner_store.question(run_id, question_id, lock=True)
            contender = asyncio.create_task(
                submit_contending_command(stores, run_id, question_id, commands[1], attempted)
            )
            async with asyncio.timeout(3):
                await wait_for_database_lock(stores, await attempted)
            winner: DecisionResult = await winner_store.answer(run_id, question_id, commands[0])
        assert contender is not None
        return [winner, await contender]
    finally:
        if contender is not None and not contender.done():
            contender.cancel()
            await asyncio.gather(contender, return_exceptions=True)


@pytest.mark.parametrize("answer_first", [True, False])
async def test_answer_racing_assumption_commits_exactly_one_revision(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore], answer_first: bool
) -> None:
    # A CAS missing from the question revision would allow both distinct commands to win.
    run_id: UUID = uuid4()
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"scope:{run_id}",
        text="Как реагировать на отказ?",
        basis="Поведение при отказе не определено",
        dependent_decision="Обработка отказа",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    await seed_run(decision_stores, run_id, question)
    answer: AnswerClarification = AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=1,
        source_versions=[],
        kind="answer",
        text="Отклонять запрос",
        basis="Решение архитектора",
    )
    assumption: AnswerClarification = answer.model_copy(
        update={
            "operation_id": uuid4(),
            "kind": "assumption",
            "assumption": AssumptionDetails(
                responsible="Архитектор",
                verification_condition="Подтверждение заказчиком",
                consequences="Ошибочный отказ",
                mitigation="Согласовать поведение до реализации",
            ),
        }
    )
    commands: list[AnswerClarification] = (
        [answer, assumption] if answer_first else [assumption, answer]
    )
    outcomes: list[DecisionResult | BaseException] = await staged_command_race(
        decision_stores, run_id, question.id, commands
    )
    winners: list[DecisionResult] = [item for item in outcomes if isinstance(item, DecisionResult)]
    assert len(winners) == 1
    assert sum(isinstance(item, Conflict) for item in outcomes) == 1
    assert (
        next(item for item in outcomes if isinstance(item, Conflict)).code
        == "stale_question_revision"
    )
    winner: DecisionResult = winners[0]
    assert winner.kind == ("answer" if answer_first else "assumption")
    winning_command: AnswerClarification = next(
        command for command in commands if command.operation_id == winner.operation_id
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        assert await store.answer(run_id, question.id, winning_command) == winner
        view: ClarificationView = await store.get(run_id)
        assert len(view.decisions) == 1
        assert len(view.risks) == (1 if winning_command.kind == "assumption" else 0)
        assert view.resume_pending
        assert (
            await store.session.scalar(
                select(func.count()).select_from(DecisionRow).where(DecisionRow.run_id == run_id)
            )
            == 1
        )
        with pytest.raises(Conflict, match="operation_payload_changed"):
            await store.answer(
                run_id, question.id, winning_command.model_copy(update={"text": "Другое решение"})
            )


async def test_first_answer_updates_requirement_while_other_blocker_remains_open(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    run_id: UUID = uuid4()
    first: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"first:{run_id}",
        text="Что делать при отказе?",
        basis="Не задано поведение",
        dependent_decision="Обработка отказа",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    await seed_run(decision_stores, run_id, first)
    second: ClarificationQuestion = first.model_copy(
        update={"id": uuid4(), "gap_key": f"second:{run_id}", "requirement_ids": [uuid4()]}
    )
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        state: ClarificationRunRow = await store.run(run_id, lock=True)
        await store.save_question(state, second)
        await store.answer(
            run_id,
            first.id,
            AnswerClarification(
                operation_id=uuid4(),
                expected_question_revision=1,
                source_versions=[],
                kind="answer",
                text="Отклонять запрос",
                basis="Ответ архитектора",
            ),
        )
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert "Отклонять запрос" in view.requirements[0].normalized_text
        assert view.requirements[0].original_text == "Исходное требование"
        assert next(item for item in view.questions if item.id == second.id).status == "open"
        assert (await store.extraction(run_id)).status == "waiting_input"


async def test_rejecting_assumption_preserves_decision_and_opens_new_revision(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    run_id: UUID = uuid4()
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"assumption:{run_id}",
        text="Как обрабатывать отказ?",
        basis="Нет условия",
        dependent_decision="Обработка отказа",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    await seed_run(decision_stores, run_id, question)
    store: SqlAlchemyClarificationStore
    async with decision_stores.open() as store:
        decision: DecisionResult = await store.answer(
            run_id,
            question.id,
            AnswerClarification(
                operation_id=uuid4(),
                expected_question_revision=1,
                source_versions=[],
                kind="assumption",
                text="Отклонять запрос",
                basis="До уточнения",
                assumption=AssumptionDetails(
                    responsible="Архитектор",
                    verification_condition="До реализации",
                    consequences="Ошибочный отказ",
                    mitigation="Проверка заказчиком",
                ),
            ),
        )
    async with decision_stores.open() as store:
        await store.resolve(
            decision.decision_id,
            ResolveAssumption(
                operation_id=uuid4(),
                expected_revision=1,
                resolution="reject",
                reason="Заказчик отклонил",
            ),
        )
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert view.cycle == 1
        assert view.questions[0].revision == 2
        assert view.questions[0].previous_basis == "Нет условия"
        assert view.questions[0].basis == "Заказчик отклонил"
        assert view.decisions[0].text == "Отклонять запрос"
        assert view.decisions[0].resolution == "rejected"
        assert view.risks[0].status == "realized"
        assert view.requirements[0].normalized_text == "Исходное требование"


async def test_invalid_commands_leave_no_decision_or_resume_request(
    decision_stores: SqlStoreSetup[SqlAlchemyClarificationStore],
) -> None:
    run_id: UUID = uuid4()
    question: ClarificationQuestion = ClarificationQuestion(
        id=uuid4(),
        gap_key=f"invalid:{run_id}",
        text="Как обрабатывать отказ?",
        basis="Нет условия",
        dependent_decision="Обработка отказа",
        blocking=True,
        requirement_ids=[uuid4()],
        sources=[],
    )
    await seed_run(decision_stores, run_id, question)
    command: AnswerClarification = AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=1,
        source_versions=[],
        kind="answer",
        text="Отклонять запрос",
        basis="Решение архитектора",
    )
    readonly: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        decision_stores.sessions, replace(decision_stores.actor, can_write=False)
    )
    foreign: SqlStoreSetup[SqlAlchemyClarificationStore] = clarification_store_setup(
        decision_stores.sessions, replace(decision_stores.actor, task_id=uuid4())
    )
    store: SqlAlchemyClarificationStore
    with pytest.raises(PermissionDenied):
        async with readonly.open() as store:
            await store.answer(run_id, question.id, command)
    with pytest.raises(Missing):
        async with foreign.open() as store:
            await store.answer(run_id, question.id, command)
    with pytest.raises(Conflict, match="stale_question_revision"):
        async with decision_stores.open() as store:
            await store.answer(
                run_id, question.id, command.model_copy(update={"expected_question_revision": 2})
            )
    with pytest.raises(Conflict, match="source_versions_changed"):
        async with decision_stores.open() as store:
            await store.answer(
                run_id,
                question.id,
                command.model_copy(
                    update={"source_versions": [SourceVersion(version_id=uuid4(), sha256="b" * 64)]}
                ),
            )
    async with decision_stores.open() as store:
        view: ClarificationView = await store.get(run_id)
        assert not view.resume_pending
        assert not view.decisions
        assert not view.risks
        assert view.questions[0].status == "open"

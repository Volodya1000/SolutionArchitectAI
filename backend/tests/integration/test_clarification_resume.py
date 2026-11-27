import asyncio
from dataclasses import replace
from typing import Final, Literal
from uuid import uuid4

import httpx
import pytest

from backend.tests.integration.test_clarification_http import (
    HttpCase,
    SqlSnapshot,
    actor_client,
    answer_command,
    sql_snapshot,
)
from backend.tests.integration.test_clarification_http import (  # pylint: disable=unused-import,useless-import-alias
    http_case_fixture as http_case_fixture,
)
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from backend.tests.integration.test_extraction_lifecycle import upload
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    AnswerClarification,
    ClarificationQuestion,
    ClarificationView,
    CommandResult,
    DecisionResult,
    ResolveAssumption,
    ResumeRun,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.protocols.extraction_protocols import ExtractionStore
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationRunRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


def resume_command(case: HttpCase, view: ClarificationView) -> ResumeRun:
    return ResumeRun(
        operation_id=uuid4(),
        question_revisions={question.id: question.revision for question in view.questions},
        source_versions=[
            SourceVersion(version_id=case.version.version_id, sha256=case.version.sha256)
        ],
    )


async def clear_resume_intent(case: HttpCase) -> None:
    view: ClarificationView = await case.service.get(case.run_id)
    store: SqlAlchemyClarificationStore
    async with case.stores.open() as store:
        await store.acknowledge(case.run_id, view.resume_version)
    assert not (await case.service.get(case.run_id)).resume_pending


@pytest.fixture(name="ready_case")
async def ready_case_fixture(http_case: HttpCase) -> HttpCase:
    await http_case.service.answer(
        http_case.run_id, http_case.question.id, answer_command(http_case)
    )
    await clear_resume_intent(http_case)
    return http_case


async def assert_rejected_resume(
    case: HttpCase,
    client: httpx.AsyncClient,
    command: ResumeRun,
    status: int,
    code: str,
) -> None:
    before: SqlSnapshot = await sql_snapshot(case, [command.operation_id])
    response: httpx.Response = await client.post(
        f"/api/extractions/{case.run_id}/resume", json=command.model_dump(mode="json")
    )
    assert response.status_code == status
    assert response.json() == {"code": code}
    assert await sql_snapshot(case, [command.operation_id]) == before


async def test_resume_waits_for_both_blockers_and_failed_attempt_does_not_poison_operation(
    http_case: HttpCase,
) -> None:
    second: ClarificationQuestion = http_case.question.model_copy(
        update={"id": uuid4(), "gap_key": f"second-resume:{uuid4()}"}
    )
    store: SqlAlchemyClarificationStore
    async with http_case.stores.open() as store:
        state: ClarificationRunRow = await store.run(http_case.run_id, lock=True)
        await store.save_question(state, second)
    command: ResumeRun = resume_command(http_case, await http_case.service.get(http_case.run_id))
    client: httpx.AsyncClient
    async with actor_client(http_case, http_case.stores.actor) as client:
        await assert_rejected_resume(http_case, client, command, 409, "blocking_questions_open")
        await http_case.service.answer(
            http_case.run_id, http_case.question.id, answer_command(http_case)
        )
        await assert_rejected_resume(http_case, client, command, 409, "blocking_questions_open")
        await http_case.service.answer(http_case.run_id, second.id, answer_command(http_case))
        before: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
        assert not before.operations
        response: httpx.Response = await client.post(
            f"/api/extractions/{http_case.run_id}/resume", json=command.model_dump(mode="json")
        )
        assert response.status_code == 200
        after: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
        assert after.view.resume_version == before.view.resume_version + 1
        assert after.view.resume_pending
        assert len(after.operations) == 1
        assert after.view.decisions == before.view.decisions


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("missing_question", "stale_question_revision"),
        ("extra_question", "stale_question_revision"),
        ("missing_sources", "source_versions_changed"),
        ("changed_hash", "source_versions_changed"),
        ("extra_source", "source_versions_changed"),
    ],
)
async def test_resume_requires_exact_question_and_source_versions(
    ready_case: HttpCase,
    change: Literal[
        "missing_question", "extra_question", "missing_sources", "changed_hash", "extra_source"
    ],
    code: str,
) -> None:
    command: ResumeRun = resume_command(ready_case, await ready_case.service.get(ready_case.run_id))
    if change == "missing_question":
        command = command.model_copy(update={"question_revisions": {}})
    elif change == "extra_question":
        command = command.model_copy(
            update={"question_revisions": command.question_revisions | {uuid4(): 1}}
        )
    elif change == "missing_sources":
        command = command.model_copy(update={"source_versions": []})
    elif change == "changed_hash":
        command = command.model_copy(
            update={
                "source_versions": [
                    SourceVersion(version_id=ready_case.version.version_id, sha256="0" * 64)
                ]
            }
        )
    else:
        extra: DocumentVersionView = await upload(ready_case.resources, "Дополнительный источник.")
        command = command.model_copy(
            update={
                "source_versions": [
                    *command.source_versions,
                    SourceVersion(version_id=extra.version_id, sha256=extra.sha256),
                ]
            }
        )
    client: httpx.AsyncClient
    async with actor_client(ready_case, ready_case.stores.actor) as client:
        await assert_rejected_resume(ready_case, client, command, 409, code)


@pytest.mark.parametrize(
    ("rejection", "status", "code"),
    [
        ("foreign", 404, "not_found"),
        ("readonly", 403, "permission_denied"),
        ("cancelled", 409, "extraction_not_resumable"),
        ("cancelling", 409, "extraction_not_resumable"),
        ("failed", 409, "extraction_not_resumable"),
    ],
)
async def test_new_resume_denies_foreign_readonly_and_unresumable_analysis_without_mutation(
    ready_case: HttpCase,
    rejection: Literal["foreign", "readonly", "cancelled", "cancelling", "failed"],
    status: int,
    code: str,
) -> None:
    command: ResumeRun = resume_command(ready_case, await ready_case.service.get(ready_case.run_id))
    actor: ActorContext = ready_case.stores.actor
    if rejection == "foreign":
        actor = replace(actor, task_id=uuid4())
    elif rejection == "readonly":
        actor = replace(actor, can_write=False)
    else:
        store: ExtractionStore
        async with ready_case.resources.stores.open() as store:
            await store.set_status(ready_case.run_id, RunStatus(rejection))
    client: httpx.AsyncClient
    async with actor_client(ready_case, actor) as client:
        await assert_rejected_resume(ready_case, client, command, status, code)


async def test_resume_rejects_old_revision_after_assumption_rejection_and_new_answer(
    http_case: HttpCase,
) -> None:
    decision: DecisionResult = await http_case.service.answer(
        http_case.run_id, http_case.question.id, answer_command(http_case, assumption=True)
    )
    stale: ResumeRun = resume_command(http_case, await http_case.service.get(http_case.run_id))
    await http_case.service.resolve(
        decision.decision_id,
        ResolveAssumption(
            operation_id=uuid4(),
            expected_revision=1,
            resolution="reject",
            reason="Условие изменилось",
        ),
    )
    current: ClarificationView = await http_case.service.get(http_case.run_id)
    assert current.questions[0].revision == 2
    answer: AnswerClarification = answer_command(http_case).model_copy(
        update={"expected_question_revision": current.questions[0].revision}
    )
    await http_case.service.answer(http_case.run_id, http_case.question.id, answer)
    await clear_resume_intent(http_case)
    client: httpx.AsyncClient
    async with actor_client(http_case, http_case.stores.actor) as client:
        await assert_rejected_resume(http_case, client, stale, 409, "stale_question_revision")


async def test_concurrent_resume_and_replay_after_source_loss_record_one_intent(
    ready_case: HttpCase,
) -> None:
    command: ResumeRun = resume_command(ready_case, await ready_case.service.get(ready_case.run_id))
    before: SqlSnapshot = await sql_snapshot(ready_case, [command.operation_id])
    client: httpx.AsyncClient
    async with actor_client(ready_case, ready_case.stores.actor) as client:
        responses: list[httpx.Response] = list(
            await asyncio.gather(
                *(
                    client.post(
                        f"/api/extractions/{ready_case.run_id}/resume",
                        json=command.model_dump(mode="json"),
                    )
                    for _attempt in range(2)
                )
            )
        )
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].content == responses[1].content
        result: CommandResult = CommandResult.model_validate_json(responses[0].content)
        assert result.operation_id == command.operation_id
        committed: SqlSnapshot = await sql_snapshot(ready_case, [command.operation_id])
        assert committed.view.resume_version == before.view.resume_version + 1
        assert committed.view.resume_pending
        assert len(committed.operations) == 1
        await asyncio.to_thread(
            (ready_case.resources.settings.storage.root / ready_case.version.storage_key).unlink
        )
        for _attempt in range(3):
            replay: httpx.Response = await client.post(
                f"/api/extractions/{ready_case.run_id}/resume", json=command.model_dump(mode="json")
            )
            assert replay.status_code == 200
            assert replay.content == responses[0].content
        operation: httpx.Response = await client.get(
            f"/api/clarification-operations/{command.operation_id}"
        )
        assert operation.status_code == 200
        assert operation.content == responses[0].content
        changed: ResumeRun = command.model_copy(update={"question_revisions": {}})
        await assert_rejected_resume(ready_case, client, changed, 409, "operation_payload_changed")
        assert await sql_snapshot(ready_case, [command.operation_id]) == committed

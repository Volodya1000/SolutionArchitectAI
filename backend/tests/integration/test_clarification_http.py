import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Final, Literal
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from sqlalchemy import select

from backend.tests.integration.test_extraction_lifecycle import ExtractionResources, upload
from backend.tests.integration.test_extraction_lifecycle import (  # pylint: disable=unused-import,useless-import-alias
    extraction_resources as extraction_resources,
)
from solution_architect_ai.application.agents.clarification_agent import ClarificationAgent
from solution_architect_ai.application.agents.extraction_sources import verify_evidence
from solution_architect_ai.application.context.clarification_context_builder import (
    ClarificationContext,
)
from solution_architect_ai.application.context.context_models import ContextFragment
from solution_architect_ai.application.errors.chat_errors import ChatError
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    ClarificationView,
    DecisionResult,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    Evidence,
    ExtractionStart,
    ExtractionView,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import ExecutionBudget
from solution_architect_ai.application.protocols.clarification_protocols import (
    ClarificationStoreFactory,
)
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.workflows.extraction_worker import ExtractionWorker
from solution_architect_ai.di.main import chat_error
from solution_architect_ai.domain.requirements import EvidenceStatus
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_factory import (
    SqlAlchemyClarificationStoreFactory,
)
from solution_architect_ai.persistence.clarifications.clarification_models import (
    ClarificationOperationRow,
    DecisionRow,
    RiskRow,
)
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.presentation.clarification_routes import router
from solution_architect_ai.presentation.document_routes import document_error

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class HttpCase:
    resources: ExtractionResources
    service: ClarificationService
    stores: SqlAlchemyClarificationStoreFactory
    version: DocumentVersionView
    run_id: UUID
    question: ClarificationQuestion

    @property
    def answer_url(self) -> str:
        return f"/api/extractions/{self.run_id}/questions/{self.question.id}/answers"


@dataclass(frozen=True)
class SqlSnapshot:
    view: ClarificationView
    extraction: ExtractionView
    decisions: tuple[str, ...]
    risks: tuple[str, ...]
    operations: tuple[tuple[UUID, str], ...]


@pytest.fixture(name="http_case")
async def http_case_fixture(
    resources: ExtractionResources, monkeypatch: pytest.MonkeyPatch
) -> HttpCase:
    agent: ClarificationAgent = await resources.container.get(ClarificationAgent)

    async def scripted_questions(
        context: ClarificationContext, _budget: ExecutionBudget
    ) -> list[ClarificationQuestion]:
        fragment: ContextFragment = context.part.fragments[-1]
        source: SourceRef = verify_evidence(
            Evidence(fragment_id=str(fragment.fragment_id), quote=fragment.text), context.part
        )
        assert source.status == EvidenceStatus.VERIFIED
        return [
            ClarificationQuestion(
                id=uuid4(),
                gap_key=f"{fragment.file_id}:http-failure-policy",
                text="Как реагировать на отказ сохранения?",
                basis="Поведение при отказе не определено",
                dependent_decision="Обработка отказа сохранения",
                blocking=True,
                requirement_ids=[UUID(sorted(context.requirement_ids)[0])],
                sources=[source],
            )
        ]

    monkeypatch.setattr(agent, "clarify", scripted_questions)
    version: DocumentVersionView = await upload(resources)
    run: ExtractionView = await resources.service.start(
        ExtractionStart(
            operation_id=uuid4(), version_ids=[version.version_id], answer_history_mode="new"
        )
    )
    resources.runs.append(run.id)
    worker: ExtractionWorker = await resources.container.get(ExtractionWorker)
    await worker.execute(run.id)
    assert (await resources.view(run.id)).status == RunStatus.WAITING_INPUT
    service: ClarificationService = await resources.container.get(ClarificationService)
    view: ClarificationView = await service.get(run.id)
    assert len(view.questions) == 1
    stores: ClarificationStoreFactory = await resources.container.get(ClarificationStoreFactory)
    assert isinstance(stores, SqlAlchemyClarificationStoreFactory)
    return HttpCase(resources, service, stores, version, run.id, view.questions[0])


def answer_command(case: HttpCase, *, assumption: bool = False) -> AnswerClarification:
    return AnswerClarification(
        operation_id=uuid4(),
        expected_question_revision=case.question.revision,
        source_versions=[
            SourceVersion(version_id=case.version.version_id, sha256=case.version.sha256)
        ],
        kind="assumption" if assumption else "answer",
        text="Повторить сохранение" if assumption else "Отклонить сохранение",
        basis="Решение архитектора",
        assumption=AssumptionDetails(
            responsible="Архитектор",
            verification_condition="Согласовать до реализации",
            consequences="Повторная запись отчёта",
            mitigation="Проверять уникальность отчёта",
        )
        if assumption
        else None,
    )


def application(container: AsyncContainer) -> FastAPI:
    app: FastAPI = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ChatError, chat_error)
    app.add_exception_handler(DocumentFailure, document_error)
    setup_dishka(container, app)
    return app


@asynccontextmanager
async def actor_client(case: HttpCase, actor: ActorContext) -> AsyncGenerator[httpx.AsyncClient]:
    provider: Provider = Provider(scope=Scope.APP)
    provider.from_context(ClarificationService)
    service: ClarificationService = ClarificationService(
        SqlAlchemyClarificationStoreFactory(case.stores.sessions, actor), case.resources.documents
    )
    container: AsyncContainer = make_async_container(
        provider, context={ClarificationService: service}
    )
    client: httpx.AsyncClient
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(container)), base_url="http://test"
        ) as client:
            yield client
    finally:
        await container.close()


async def sql_snapshot(case: HttpCase, operation_ids: list[UUID]) -> SqlSnapshot:
    # A fresh PostgreSQL transaction observes only mutations committed by the request.
    store: SqlAlchemyClarificationStore
    async with case.stores.open() as store:
        view: ClarificationView = await store.get(case.run_id)
        extraction: ExtractionView = ExtractionView.model_validate_json(
            (await store.extraction(case.run_id)).snapshot_json
        )
        decisions: tuple[str, ...] = tuple(
            await store.session.scalars(
                select(DecisionRow.snapshot_json).where(DecisionRow.run_id == case.run_id)
            )
        )
        risks: tuple[str, ...] = tuple(
            await store.session.scalars(
                select(RiskRow.snapshot_json)
                .join(DecisionRow, DecisionRow.id == RiskRow.decision_id)
                .where(DecisionRow.run_id == case.run_id)
            )
        )
        rows: list[ClarificationOperationRow] = list(
            await store.session.scalars(
                select(ClarificationOperationRow)
                .where(
                    ClarificationOperationRow.task_id == case.stores.actor.task_id,
                    ClarificationOperationRow.operation_id.in_(operation_ids),
                )
                .order_by(ClarificationOperationRow.operation_id)
            )
        )
        return SqlSnapshot(
            view,
            extraction,
            decisions,
            risks,
            tuple((row.operation_id, row.result_json) for row in rows),
        )


class DropCommittedResponse(httpx.AsyncBaseTransport):
    def __init__(self, app: FastAPI) -> None:
        self.inner: httpx.ASGITransport = httpx.ASGITransport(app=app)
        self.committed_body: bytes | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response: httpx.Response = await self.inner.handle_async_request(request)
        if request.method == "POST" and self.committed_body is None:
            # ASGI has finished, including the store context manager's SQL commit.
            assert response.status_code == 200
            self.committed_body = await response.aread()
            await response.aclose()
            raise httpx.ReadError("response lost after server commit", request=request)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def assert_race_commit(
    commands: list[AnswerClarification],
    responses: list[httpx.Response],
    before: SqlSnapshot,
    after: SqlSnapshot,
) -> AnswerClarification:
    assert sorted(response.status_code for response in responses) == [200, 409]
    winning_index: int = next(
        index for index, response in enumerate(responses) if response.status_code == 200
    )
    winner: AnswerClarification = commands[winning_index]
    loser: AnswerClarification = commands[1 - winning_index]
    decision: DecisionResult = DecisionResult.model_validate_json(responses[winning_index].content)
    assert responses[1 - winning_index].json() == {"code": "stale_question_revision"}
    assert after.view.decisions == [decision]
    assert len(after.decisions) == 1
    assert len(after.risks) == len(after.view.risks) == (1 if winner.kind == "assumption" else 0)
    assert after.view.questions[0].status == (
        "assumed" if winner.kind == "assumption" else "answered"
    )
    assert after.view.resume_pending
    assert after.view.resume_version == before.view.resume_version + 1
    assert [operation_id for operation_id, _result in after.operations] == [winner.operation_id]
    requirement: RequirementView = next(
        item for item in after.view.requirements if item.id in decision.requirement_ids
    )
    assert winner.text in requirement.normalized_text
    assert all(loser.text not in item.normalized_text for item in after.view.requirements)
    return winner


async def race_verified_requests(
    case: HttpCase,
    client: httpx.AsyncClient,
    commands: list[AnswerClarification],
    monkeypatch: pytest.MonkeyPatch,
) -> list[httpx.Response]:
    barrier: asyncio.Barrier = asyncio.Barrier(2)
    original: Callable[[list[SourceVersion]], Awaitable[None]] = case.service.verify_versions

    async def verified_together(sources: list[SourceVersion]) -> None:
        await original(sources)
        await barrier.wait()

    monkeypatch.setattr(case.service, "verify_versions", verified_together)
    try:
        async with asyncio.timeout(10):
            return list(
                await asyncio.gather(
                    *(
                        client.post(case.answer_url, json=command.model_dump(mode="json"))
                        for command in commands
                    )
                )
            )
    finally:
        monkeypatch.setattr(case.service, "verify_versions", original)


@pytest.mark.parametrize("assumption_first", [False, True])
async def test_http_answer_and_assumption_race_has_one_committed_winner(
    http_case: HttpCase, monkeypatch: pytest.MonkeyPatch, assumption_first: bool
) -> None:
    commands: list[AnswerClarification] = [
        answer_command(http_case, assumption=assumption_first),
        answer_command(http_case, assumption=not assumption_first),
    ]
    operation_ids: list[UUID] = [command.operation_id for command in commands]
    before: SqlSnapshot = await sql_snapshot(http_case, operation_ids)
    client: httpx.AsyncClient
    _attempt: int
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application(http_case.resources.container)),
        base_url="http://test",
    ) as client:
        responses: list[httpx.Response] = await race_verified_requests(
            http_case, client, commands, monkeypatch
        )
        after: SqlSnapshot = await sql_snapshot(http_case, operation_ids)
        winner: AnswerClarification = assert_race_commit(commands, responses, before, after)
        for _attempt in range(3):
            replay: httpx.Response = await client.post(
                http_case.answer_url, json=winner.model_dump(mode="json")
            )
            assert replay.status_code == 200
            assert DecisionResult.model_validate_json(replay.content) == after.view.decisions[0]
        loser: AnswerClarification = next(
            command for command in commands if command.operation_id != winner.operation_id
        )
        missing: httpx.Response = await client.get(
            f"/api/clarification-operations/{loser.operation_id}"
        )
        assert missing.status_code == 404
        assert await sql_snapshot(http_case, operation_ids) == after


async def test_http_lost_committed_response_replays_after_source_disappears(
    http_case: HttpCase,
) -> None:
    command: AnswerClarification = answer_command(http_case, assumption=True)
    transport: DropCommittedResponse = DropCommittedResponse(
        application(http_case.resources.container)
    )
    client: httpx.AsyncClient
    _attempt: int
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="response lost after server commit"):
            await client.post(http_case.answer_url, json=command.model_dump(mode="json"))
        committed: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
        assert len(committed.decisions) == len(committed.risks) == len(committed.operations) == 1
        assert committed.view.resume_pending
        assert committed.view.resume_version == 1
        assert transport.committed_body is not None
        assert (
            DecisionResult.model_validate_json(transport.committed_body)
            == committed.view.decisions[0]
        )
        await asyncio.to_thread(
            (http_case.resources.settings.storage.root / http_case.version.storage_key).unlink
        )
        for _attempt in range(3):
            replay: httpx.Response = await client.post(
                http_case.answer_url, json=command.model_dump(mode="json")
            )
            assert replay.status_code == 200
            assert replay.content == transport.committed_body
        operation: httpx.Response = await client.get(
            f"/api/clarification-operations/{command.operation_id}"
        )
        assert operation.status_code == 200
        assert operation.content == transport.committed_body
        changed: AnswerClarification = command.model_copy(update={"text": "Изменённое решение"})
        conflict: httpx.Response = await client.post(
            http_case.answer_url, json=changed.model_dump(mode="json")
        )
        assert conflict.status_code == 409
        assert conflict.json() == {"code": "operation_payload_changed"}
        assert await sql_snapshot(http_case, [command.operation_id]) == committed


@pytest.mark.parametrize(
    ("rejection", "status", "code"),
    [
        ("stale", 409, "stale_question_revision"),
        ("source", 409, "source_versions_changed"),
        ("foreign", 404, "not_found"),
        ("readonly", 403, "permission_denied"),
    ],
)
async def test_http_rejected_answer_leaves_question_requirements_and_resume_unchanged(
    http_case: HttpCase,
    rejection: Literal["stale", "source", "foreign", "readonly"],
    status: int,
    code: str,
) -> None:
    command: AnswerClarification = answer_command(http_case, assumption=True)
    actor: ActorContext = http_case.stores.actor
    if rejection == "stale":
        command = command.model_copy(update={"expected_question_revision": 2})
    elif rejection == "source":
        command = command.model_copy(
            update={
                "source_versions": [
                    SourceVersion(version_id=http_case.version.version_id, sha256="0" * 64)
                ]
            }
        )
    elif rejection == "foreign":
        actor = replace(actor, task_id=uuid4())
    else:
        actor = replace(actor, can_write=False)
    before: SqlSnapshot = await sql_snapshot(http_case, [command.operation_id])
    client: httpx.AsyncClient
    async with actor_client(http_case, actor) as client:
        response: httpx.Response = await client.post(
            http_case.answer_url, json=command.model_dump(mode="json")
        )
    assert response.status_code == status
    assert response.json() == {"code": code}
    assert await sql_snapshot(http_case, [command.operation_id]) == before
    assert not before.decisions
    assert not before.risks
    assert not before.operations
    assert not before.view.resume_pending
    assert before.view.questions[0].status == "open"

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
from dishka import AsyncContainer, Provider, Scope, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from sqlalchemy import select

from backend.test_helpers.extraction_resources import ExtractionResources
from backend.test_helpers.sql_store_setup import SqlStoreSetup, clarification_store_setup
from solution_architect_ai.application.errors.chat_errors import ChatError
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.models.clarification_models import (
    ActorContext,
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    ClarificationView,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
)
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.di.main import chat_error
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


@dataclass(frozen=True)
class HttpCase:
    resources: ExtractionResources
    service: ClarificationService
    stores: SqlStoreSetup[SqlAlchemyClarificationStore]
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
        clarification_store_setup(case.stores.sessions, actor), case.resources.documents
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

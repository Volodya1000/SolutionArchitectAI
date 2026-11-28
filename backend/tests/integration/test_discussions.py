import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from backend.test_helpers.discussion_resources import (
    Resources,
    content_chunks,
    seed_analysis,
    upload,
)
from backend.test_helpers.sql_store_setup import (
    SqlStoreSetup,
    chat_store_setup,
    discussion_store_setup,
)
from solution_architect_ai.application.context.discussion_context_builder import (
    DiscussionContextBuilder,
)
from solution_architect_ai.application.errors.chat_errors import (
    ChatError,
    Conflict,
    GenerationFailure,
    Missing,
)
from solution_architect_ai.application.errors.clarification_errors import PermissionDenied
from solution_architect_ai.application.errors.document_errors import DocumentFailure
from solution_architect_ai.application.generation import RunWorker
from solution_architect_ai.application.models.chat_dto import (
    ChatView,
    MessageView,
    ModelStatus,
    PendingRun,
    RunView,
    StartRun,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
)
from solution_architect_ai.application.models.discussion_models import (
    CreateDiscussion,
    DiscussionView,
    RequirementSubject,
    SourceSubject,
)
from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
    UploadDocument,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionView,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.protocols.chat_protocols import ChatStore, Chunk
from solution_architect_ai.application.retry import GenerationPolicy
from solution_architect_ai.application.services.clarification_service import ClarificationService
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.di.main import chat_error
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.messages import MessageRole
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunErrorCode, RunStatus
from solution_architect_ai.infrastructure.context import LangChainTokenCounter
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.models import ChatRow
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID
from solution_architect_ai.persistence.store import SqlAlchemyStore
from solution_architect_ai.presentation.api import create_http_app
from solution_architect_ai.presentation.document_routes import document_error

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


async def test_same_source_keeps_analysis_a_b_and_direct_context_separate(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    analysis_a: UUID
    analysis_b: UUID
    requirement_a: UUID
    requirement_b: UUID
    analysis_a, requirement_a = await seed_analysis(resources, version, "A: publish daily")
    analysis_b, requirement_b = await seed_analysis(resources, version, "B: publish monthly")
    assert requirement_a != requirement_b
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    builder: DiscussionContextBuilder = DiscussionContextBuilder(resources.discussions)
    analysis_id: UUID | None
    for analysis_id in (analysis_a, analysis_b, None):
        chat: ChatView = await resources.discussions.create(
            CreateDiscussion(
                operation_id=uuid4(),
                subject=SourceSubject(
                    kind="source",
                    version_id=version.version_id,
                    fragment_id=parsed.fragments[0].fragment_id,
                    analysis_id=analysis_id,
                ),
            )
        )
        view: DiscussionView | None = await resources.discussions.get(chat.id)
        assert view is not None
        assert view.analysis_id == analysis_id
        assert view.history_id == analysis_id
        messages: list[MessageView] = await builder.messages(chat.id)
        context: str = "\n".join(message.content for message in messages)
        assert "R03 Reports" in context
        assert "R04 Reports" in context
        assert ("A: publish daily" in context) == (analysis_id == analysis_a)
        assert ("B: publish monthly" in context) == (analysis_id == analysis_b)


async def test_requirement_discussion_without_questions_is_pinned_after_upload(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    run_id: UUID
    requirement_id: UUID
    run_id, requirement_id = await seed_analysis(resources, version, None)
    command: CreateDiscussion = CreateDiscussion(
        operation_id=uuid4(),
        subject=RequirementSubject(
            kind="requirement",
            run_id=run_id,
            requirement_id=requirement_id,
        ),
    )
    chat: ChatView = await resources.discussions.create(command)
    newer: DocumentVersionView = await upload(resources, version.file_id)
    assert newer.version_id != version.version_id
    reopened: DiscussionView | None = await DiscussionService(
        resources.stores,
        resources.documents,
        ClarificationService(resources.clarifications, resources.documents),
    ).get(chat.id)
    assert reopened is not None
    assert reopened.version_ids == [version.version_id]
    assert reopened.analysis_id == run_id
    assert reopened.requirement_id == requirement_id
    assert str(run_id) in reopened.backlink
    context: list[MessageView] = await DiscussionContextBuilder(resources.discussions).messages(
        chat.id
    )
    assert str(version.version_id) in context[1].content
    assert str(newer.version_id) not in context[1].content


async def test_operation_replay_and_intentional_new_chat_are_distinct(resources: Resources) -> None:
    version: DocumentVersionView = await upload(resources)
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    command: CreateDiscussion = CreateDiscussion(
        operation_id=uuid4(),
        subject=SourceSubject(
            kind="source",
            version_id=version.version_id,
            fragment_id=parsed.fragments[0].fragment_id,
        ),
    )
    chats: tuple[ChatView, ChatView] = await asyncio.gather(
        resources.discussions.create(command), resources.discussions.create(command)
    )
    assert chats[0] == chats[1]
    assert await resources.discussions.operation(command.operation_id) == chats[0]
    second: ChatView = await resources.discussions.create(
        command.model_copy(update={"operation_id": uuid4()})
    )
    assert second.id != chats[0].id
    with pytest.raises(Conflict, match="operation_payload_changed"):
        await resources.discussions.create(
            command.model_copy(
                update={
                    "subject": command.subject.model_copy(update={"fragment_id": uuid4()}),
                }
            )
        )


async def test_foreign_scope_version_and_readonly_creation_are_rejected(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    command: CreateDiscussion = CreateDiscussion(
        operation_id=uuid4(),
        subject=SourceSubject(
            kind="source",
            version_id=version.version_id,
            fragment_id=parsed.fragments[0].fragment_id,
        ),
    )
    chat: ChatView = await resources.discussions.create(command)
    foreign: SqlStoreSetup[SqlAlchemyDiscussionStore] = discussion_store_setup(
        resources.stores.sessions,
        replace(resources.stores.actor, task_id=uuid4()),
    )
    store: SqlAlchemyDiscussionStore
    async with foreign.open() as store:
        with pytest.raises(Missing):
            await store.get(chat.id)
        with pytest.raises(Missing):
            await store.check_version(version.version_id)
        with pytest.raises(Missing):
            await store.operation(command.operation_id)
    readonly: SqlStoreSetup[SqlAlchemyDiscussionStore] = discussion_store_setup(
        resources.stores.sessions,
        replace(resources.stores.actor, can_write=False),
    )
    service: DiscussionService = DiscussionService(
        readonly,
        resources.documents,
        resources.discussions.clarification_service,
    )
    with pytest.raises(PermissionDenied):
        await service.create(command.model_copy(update={"operation_id": uuid4()}))


async def test_source_cannot_borrow_an_unrelated_analyses_history(resources: Resources) -> None:
    version: DocumentVersionView = await upload(resources)
    other: DocumentVersionView = await upload(resources)
    run_id: UUID
    requirement_id: UUID
    run_id, requirement_id = await seed_analysis(resources, other, "Foreign version answer")
    assert requirement_id
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    with pytest.raises(Missing, match="analysis_source_version"):
        await resources.discussions.create(
            CreateDiscussion(
                operation_id=uuid4(),
                subject=SourceSubject(
                    kind="source",
                    version_id=version.version_id,
                    fragment_id=parsed.fragments[0].fragment_id,
                    analysis_id=run_id,
                ),
            )
        )


async def test_missing_source_is_explicit_and_operation_replay_survives_it(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    command: CreateDiscussion = CreateDiscussion(
        operation_id=uuid4(),
        subject=SourceSubject(
            kind="source",
            version_id=version.version_id,
            fragment_id=parsed.fragments[0].fragment_id,
        ),
    )
    chat: ChatView = await resources.discussions.create(command)
    (resources.directory / version.storage_key).unlink()
    assert await resources.discussions.create(command) == chat
    failure: pytest.ExceptionInfo[GenerationFailure]
    with pytest.raises(GenerationFailure) as failure:
        await DiscussionContextBuilder(resources.discussions).messages(chat.id)
    assert failure.value.code == RunErrorCode.DISCUSSION_SOURCE_UNAVAILABLE


async def test_ordinary_chats_have_no_discussion_context(resources: Resources) -> None:
    store: SqlAlchemyDiscussionStore
    async with resources.stores.open() as store:
        chat: ChatRow = ChatRow(task_id=DEFAULT_TASK_ID, title="Ordinary")
        store.session.add(chat)
        await store.session.flush()
        chat_id: UUID = chat.id
    assert await resources.discussions.get(chat_id) is None
    assert await DiscussionContextBuilder(resources.discussions).messages(chat_id) == []


async def test_http_discussion_roundtrip_and_rejects_forged_author(resources: Resources) -> None:
    version: DocumentVersionView = await upload(resources)
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    command: CreateDiscussion = CreateDiscussion(
        operation_id=uuid4(),
        subject=SourceSubject(
            kind="source",
            version_id=version.version_id,
            fragment_id=parsed.fragments[0].fragment_id,
        ),
    )
    provider: Provider = Provider(scope=Scope.APP)
    provider.from_context(DiscussionService)
    provider.from_context(ClarificationService)
    container: AsyncContainer = make_async_container(
        provider,
        context={
            DiscussionService: resources.discussions,
            ClarificationService: resources.discussions.clarification_service,
        },
    )
    app: FastAPI = create_http_app()
    app.add_exception_handler(ChatError, chat_error)
    app.add_exception_handler(DocumentFailure, document_error)
    setup_dishka(container, app)
    try:
        client: httpx.AsyncClient
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response: httpx.Response = await client.post(
                "/api/discussions", json=command.model_dump(mode="json")
            )
            assert response.status_code == 201
            chat: ChatView = ChatView.model_validate_json(response.content)
            reopened: httpx.Response = await client.get(f"/api/chats/{chat.id}/discussion")
            assert reopened.status_code == 200
            view: DiscussionView = DiscussionView.model_validate_json(reopened.content)
            assert view.fragment_id == parsed.fragments[0].fragment_id
            assert view.version_ids == [version.version_id]
            recovered: httpx.Response = await client.get(
                f"/api/discussion-operations/{command.operation_id}"
            )
            assert ChatView.model_validate_json(recovered.content) == chat
            forged: httpx.Response = await client.post(
                "/api/discussions",
                json={
                    **command.model_dump(mode="json"),
                    "author_id": str(uuid4()),
                },
            )
            assert forged.status_code == 422
            assert [(item["loc"], item["type"]) for item in forged.json()["detail"]] == [
                (["body", "author_id"], "extra_forbidden")
            ]
            answer: httpx.Response = await client.post(
                f"/api/extractions/{chat.id}/questions/{uuid4()}/answers",
                json=AnswerClarification(
                    operation_id=uuid4(),
                    expected_question_revision=1,
                    source_versions=[],
                    kind="answer",
                    text="Forged chat answer",
                    basis="Discussion",
                ).model_dump(mode="json"),
            )
            assert answer.status_code == 404
    finally:
        await container.close()


class RecordingLLM:
    def __init__(self) -> None:
        self.requests: list[list[MessageView]] = []

    async def status(self) -> ModelStatus:
        return ModelStatus(model="recording", available=True)

    @asynccontextmanager
    async def stream(self, messages: list[MessageView]) -> AsyncGenerator[AsyncIterator[Chunk]]:
        self.requests.append(messages)

        async def chunks() -> AsyncGenerator[Chunk]:
            yield Chunk(text="Evidence explanation", finish="stop")

        yield chunks()


async def test_worker_supplies_pinned_source_and_fails_visibly_if_it_disappears(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await upload(resources)
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    chat: ChatView = await resources.discussions.create(
        CreateDiscussion(
            operation_id=uuid4(),
            subject=SourceSubject(
                kind="source",
                version_id=version.version_id,
                fragment_id=parsed.fragments[1].fragment_id,
            ),
        )
    )
    stores: SqlStoreSetup[SqlAlchemyStore] = chat_store_setup(resources.stores.sessions)
    llm: RecordingLLM = RecordingLLM()
    tokens: LangChainTokenCounter = LangChainTokenCounter(2)
    policy: GenerationPolicy = GenerationPolicy(
        concurrency=1, deadline=30, retries=0, requests=1, backoff=0, input_budget=12000
    )
    worker: RunWorker = RunWorker(
        stores,
        llm,
        policy,
        tokens,
        discussion_context=DiscussionContextBuilder(resources.discussions),
    )
    store: ChatStore
    async with stores.open() as store:
        started: RunView = await store.start(
            chat.id,
            StartRun(command_id=uuid4(), content="Explain R03 and R04"),
            "recording",
            "test",
        )
    await worker.execute(
        PendingRun(id=started.id, status=RunStatus.QUEUED, created_at=started.created_at)
    )
    assert len(llm.requests) == 1

    assert tokens.count(llm.requests[0]) <= policy.input_budget
    assert "R03 Reports" in llm.requests[0][1].content
    assert "R04 Reports" in llm.requests[0][1].content
    assert str(version.version_id) not in llm.requests[0][1].content
    assert version.sha256 not in llm.requests[0][1].content
    assert "Explain R03 and R04" in llm.requests[0][-1].content
    async with stores.open() as store:
        completed: RunView = await store.queries.get_run(started.id)
        assert completed.status == RunStatus.COMPLETED
        next_run: RunView = await store.start(
            chat.id, StartRun(command_id=uuid4(), content="Again"), "recording", "test"
        )
    (resources.directory / version.storage_key).unlink()
    await worker.execute(
        PendingRun(id=next_run.id, status=RunStatus.QUEUED, created_at=next_run.created_at)
    )
    async with stores.open() as store:
        failed: RunView = await store.queries.get_run(next_run.id)
    assert failed.status == RunStatus.FAILED
    assert failed.error_code == RunErrorCode.DISCUSSION_SOURCE_UNAVAILABLE
    assert len(llm.requests) == 1


async def reporting_sibling_sources(
    resources: Resources, document: ParsedDocument
) -> list[SourceRef]:
    return [
        await resources.discussions.source_reference(document.version_id, fragment.fragment_id)
        for fragment in document.fragments
        if any(
            identifier in fragment.text
            for identifier in ("| R-01 |", "| R-02 |", "| R-04 |", "| R-05 |")
        )
    ]


async def test_reporting_context_contains_r03_r04_without_unrelated_requirement_payload(
    resources: Resources,
) -> None:
    version: DocumentVersionView = await resources.documents.upload(
        UploadDocument(operation_id=uuid4(), filename="reporting.md", mime_type="text/markdown"),
        content_chunks(
            (Path(__file__).parents[3] / "docs/examples/reporting-system.md").read_bytes()
        ),
    )
    document: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    selected_id: UUID = next(
        fragment.fragment_id for fragment in document.fragments if "| R-03 |" in fragment.text
    )
    run_id: UUID
    requirement_id: UUID
    run_id, requirement_id = await seed_analysis(resources, version, None)
    selected: SourceRef = await resources.discussions.source_reference(
        version.version_id, selected_id
    )
    far: SourceRef = await resources.discussions.source_reference(
        version.version_id,
        next(
            fragment.fragment_id for fragment in document.fragments if "| SEC-08 |" in fragment.text
        ),
    )
    store: SqlAlchemyClarificationStore
    async with resources.clarifications.open() as store:
        row: ExtractionRow = await store.extraction(run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.requirements[0].sources = [selected]
        sibling: SourceRef
        for sibling in await reporting_sibling_sources(resources, document):
            view.requirements.append(
                RequirementView(
                    id=uuid4(),
                    category=RequirementCategory.FUNCTIONAL,
                    original_text=sibling.quote,
                    normalized_text=sibling.quote,
                    sources=[sibling],
                )
            )
        view.requirements.append(
            RequirementView(
                id=uuid4(),
                category=RequirementCategory.CONSTRAINT,
                original_text="Unrelated requirement payload",
                normalized_text="Unrelated requirement payload",
                sources=[far],
            )
        )
        row.snapshot_json = view.model_dump_json()
    chat: ChatView = await resources.discussions.create(
        CreateDiscussion(
            operation_id=uuid4(),
            subject=SourceSubject(
                kind="source",
                version_id=version.version_id,
                fragment_id=selected_id,
                analysis_id=run_id,
            ),
        )
    )
    messages: list[MessageView] = await DiscussionContextBuilder(resources.discussions).messages(
        chat.id
    )
    assert "| R-03 |" in messages[1].content
    assert "| R-04 |" in messages[1].content
    assert str(requirement_id) in messages[1].content
    assert "Unrelated requirement payload" not in messages[1].content
    assert '"context_manifest"' in messages[1].content
    question: MessageView = MessageView(
        id=uuid4(),
        role=MessageRole.USER,
        content="Explain the relationship between R03 and R04",
        position=0,
        incomplete=False,
    )
    assert LangChainTokenCounter(2).count([*messages, question]) <= 5376


@pytest.fixture(name="resources")
def discussion_resources_fixture(discussion_resources: Resources) -> Resources:
    return discussion_resources

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from langchain_openai import ChatOpenAI
from pydantic import TypeAdapter

from backend.tests.integration.test_discussions import Resources, content_chunks, seed_analysis
from backend.tests.integration.test_discussions import (  # pylint: disable=unused-import,useless-import-alias
    discussion_resources as discussion_resources,
)
from solution_architect_ai.application.context.discussion_context_builder import (
    DiscussionContextBuilder,
)
from solution_architect_ai.application.models.chat_dto import ChatView, MessageView
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    AssumptionDetails,
    ClarificationQuestion,
    ClarificationView,
    SourceVersion,
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
from solution_architect_ai.application.protocols.chat_protocols import Chunk
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory
from solution_architect_ai.infrastructure.llm import LangChainLLM
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.presentation.discussion_routes import router

pytestmark: Final[list[pytest.MarkDecorator]] = [pytest.mark.anyio, pytest.mark.integration]


@dataclass(frozen=True)
class ScopeCase:
    resources: Resources
    run_id: UUID
    version: DocumentVersionView
    requirements: tuple[UUID, UUID]
    sources: tuple[SourceRef, SourceRef]


@pytest.fixture(name="scope_case")
async def scope_case_fixture(resources: Resources) -> ScopeCase:
    version: DocumentVersionView = await resources.documents.upload(
        UploadDocument(operation_id=uuid4(), filename="scope.md", mime_type="text/markdown"),
        content_chunks(b"Retention is 30 days.\n\nAvailability is 99.9 percent.\n"),
    )
    run_id: UUID
    requirement_id: UUID
    run_id, requirement_id = await seed_analysis(resources, version, None)
    document: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    sources: tuple[SourceRef, SourceRef] = (
        await resources.discussions.source_reference(
            version.version_id, document.fragments[0].fragment_id
        ),
        await resources.discussions.source_reference(
            version.version_id, document.fragments[1].fragment_id
        ),
    )
    identifiers: tuple[UUID, UUID] = (requirement_id, uuid4())
    store: SqlAlchemyClarificationStore
    async with resources.clarifications.open() as store:
        row: ExtractionRow = await store.extraction(run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.requirements = [
            RequirementView(
                id=identifier,
                category=RequirementCategory.FUNCTIONAL,
                original_text=source.quote,
                normalized_text=source.quote,
                sources=[source],
            )
            for identifier, source in zip(identifiers, sources, strict=True)
        ]
        row.snapshot_json = view.model_dump_json()
    return ScopeCase(resources, run_id, version, identifiers, sources)


async def record_scoped_assumptions(case: ScopeCase) -> None:
    questions: list[ClarificationQuestion] = [
        ClarificationQuestion(
            id=uuid4(),
            gap_key=f"scope:{identifier}",
            text=f"Clarify {source.quote}",
            basis="A decision is required",
            dependent_decision=source.quote,
            blocking=True,
            requirement_ids=[identifier],
            sources=[source],
        )
        for identifier, source in zip(case.requirements, case.sources, strict=True)
    ]
    store: SqlAlchemyClarificationStore
    async with case.resources.clarifications.open() as store:
        await store.save_questions(case.run_id, questions)
        question: ClarificationQuestion
        for question in questions:
            await store.answer(
                case.run_id,
                question.id,
                AnswerClarification(
                    operation_id=uuid4(),
                    expected_question_revision=1,
                    source_versions=[
                        SourceVersion(
                            version_id=case.version.version_id, sha256=case.version.sha256
                        )
                    ],
                    kind="assumption",
                    text=f"Assume {question.dependent_decision}",
                    basis="Pending confirmation",
                    assumption=AssumptionDetails(
                        responsible="Architect",
                        verification_condition="Customer review",
                        consequences=f"Risk for {question.dependent_decision}",
                        mitigation="Confirm before implementation",
                    ),
                ),
            )


async def selected_chat(case: ScopeCase, kind: Literal["requirement", "source"]) -> ChatView:
    return await case.resources.discussions.create(
        CreateDiscussion(
            operation_id=uuid4(),
            subject=RequirementSubject(
                kind="requirement", run_id=case.run_id, requirement_id=case.requirements[0]
            )
            if kind == "requirement"
            else SourceSubject(
                kind="source",
                version_id=case.version.version_id,
                fragment_id=UUID(case.sources[0].fragment_id),
                analysis_id=case.run_id,
            ),
        )
    )


@pytest.fixture(name="scope_client")
async def scope_client_fixture(resources: Resources) -> AsyncIterator[httpx.AsyncClient]:
    provider: Provider = Provider(scope=Scope.APP)
    provider.from_context(DiscussionService)
    container: AsyncContainer = make_async_container(
        provider, context={DiscussionService: resources.discussions}
    )
    app: FastAPI = FastAPI()
    app.include_router(router)
    setup_dishka(container, app)
    try:
        client: httpx.AsyncClient
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await container.close()


@pytest.mark.parametrize("kind", ["requirement", "source"])
async def test_discussion_endpoint_and_model_share_only_the_selected_subject_scope(
    scope_case: ScopeCase, scope_client: httpx.AsyncClient, kind: Literal["requirement", "source"]
) -> None:
    await record_scoped_assumptions(scope_case)
    chat: ChatView = await selected_chat(scope_case, kind)
    response: httpx.Response = await scope_client.get(
        f"/api/chats/{chat.id}/discussion/clarifications"
    )
    assert response.status_code == 200
    scoped: ClarificationView = ClarificationView.model_validate_json(response.content)
    assert [item.id for item in scoped.requirements] == [scope_case.requirements[0]]
    assert len(scoped.questions) == len(scoped.decisions) == len(scoped.risks) == 1
    assert scoped.questions[0].requirement_ids == [scope_case.requirements[0]]
    assert scoped.decisions[0].question_id == scoped.questions[0].id
    assert scoped.risks[0].decision_id == scoped.decisions[0].decision_id
    global_state: ClarificationView = (
        await scope_case.resources.discussions.clarification_service.get(scope_case.run_id)
    )
    assert (
        len(global_state.requirements)
        == len(global_state.questions)
        == len(global_state.risks)
        == 2
    )
    messages: list[MessageView] = await DiscussionContextBuilder(
        scope_case.resources.discussions
    ).messages(chat.id)
    payload: dict[str, object] = TypeAdapter(dict[str, object]).validate_json(messages[1].content)
    analysis: dict[str, object] = TypeAdapter(dict[str, object]).validate_python(
        payload["analysis"]
    )
    requirements: list[RequirementView] = TypeAdapter(list[RequirementView]).validate_python(
        analysis["requirements"]
    )
    assert [item.id for item in requirements] == [scope_case.requirements[0]]
    assert str(scope_case.requirements[1]) not in messages[1].content
    assert (
        scope_case.sources[1].quote in messages[1].content
    )  # Neighbor remains authentic source background.
    assert "Availability" not in str(analysis)
    subject: dict[str, object] = TypeAdapter(dict[str, object]).validate_python(payload["subject"])
    assert str(scope_case.run_id) in str(subject["backlink"])
    assert str(subject["backlink"]).startswith(
        "/documents?" if kind == "source" else "/requirements?"
    )


async def test_legacy_uninitialized_scope_still_returns_selected_requirement(
    scope_case: ScopeCase, scope_client: httpx.AsyncClient
) -> None:
    chat: ChatView = await selected_chat(scope_case, "requirement")
    response: httpx.Response = await scope_client.get(
        f"/api/chats/{chat.id}/discussion/clarifications"
    )
    assert response.status_code == 200
    scoped: ClarificationView = ClarificationView.model_validate_json(response.content)
    assert not scoped.initialized
    assert [item.id for item in scoped.requirements] == [scope_case.requirements[0]]


async def test_source_only_discussion_has_no_analysis_scope(
    scope_case: ScopeCase, scope_client: httpx.AsyncClient
) -> None:
    chat: ChatView = await scope_case.resources.discussions.create(
        CreateDiscussion(
            operation_id=uuid4(),
            subject=SourceSubject(
                kind="source",
                version_id=scope_case.version.version_id,
                fragment_id=UUID(scope_case.sources[0].fragment_id),
            ),
        )
    )
    response: httpx.Response = await scope_client.get(
        f"/api/chats/{chat.id}/discussion/clarifications"
    )
    assert response.status_code == 200
    assert response.json() is None


async def test_discussion_keeps_full_subject_title_with_a_bounded_chat_label(
    scope_case: ScopeCase,
) -> None:
    title: str = (
        "Retention is 30 days and the record is available for the complete retention period. " * 3
    )
    store: SqlAlchemyClarificationStore
    async with scope_case.resources.clarifications.open() as store:
        row: ExtractionRow = await store.extraction(scope_case.run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.requirements[0].normalized_text = title
        row.snapshot_json = view.model_dump_json()
    chat: ChatView = await selected_chat(scope_case, "requirement")
    discussion: DiscussionView | None = await scope_case.resources.discussions.get(chat.id)
    assert discussion is not None
    assert discussion.title == title
    assert len(chat.title) <= 120


async def test_actual_adapter_keeps_candidate_verification_separate_from_authentic_source(
    scope_case: ScopeCase,
) -> None:
    candidate: SourceRef = SourceRef(
        file_id=scope_case.sources[0].file_id,
        version_id=scope_case.version.version_id,
        sha256=scope_case.version.sha256,
        fragment_id=scope_case.sources[0].fragment_id,
        locator=scope_case.sources[0].locator,
        quote="Retention is 90 days.",
        status=EvidenceStatus.UNVERIFIED,
        reason="quote_not_in_context",
    )
    store: SqlAlchemyClarificationStore
    async with scope_case.resources.clarifications.open() as store:
        row: ExtractionRow = await store.extraction(scope_case.run_id, lock=True)
        view: ExtractionView = ExtractionView.model_validate_json(row.snapshot_json)
        view.requirements[0].original_text = "Retention is 90 days."
        view.requirements[0].normalized_text = "Retention is 90 days."
        view.requirements[0].sources = [candidate]
        row.snapshot_json = view.model_dump_json()
    chat: ChatView = await selected_chat(scope_case, "requirement")
    messages: list[MessageView] = await DiscussionContextBuilder(
        scope_case.resources.discussions
    ).messages(chat.id)
    payload: dict[str, object] = await captured_model_context(messages)
    analysis: dict[str, object] = TypeAdapter(dict[str, object]).validate_python(
        payload["analysis"]
    )
    requirements: list[RequirementView] = TypeAdapter(list[RequirementView]).validate_python(
        analysis["requirements"]
    )
    assert requirements[0].sources[0] == candidate
    authentic: list[SourceRef] = TypeAdapter(list[SourceRef]).validate_python(
        payload["source_fragments"]
    )
    assert authentic[0].quote == "Retention is 30 days."
    assert authentic[0].status == EvidenceStatus.VERIFIED
    assert authentic[0].reason is None


async def captured_model_context(messages: list[MessageView]) -> dict[str, object]:
    requests: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(TypeAdapter(dict[str, object]).validate_json(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                'data: {"id":"scope","object":"chat.completion.chunk","created":1,"model":"scope",'
                '"choices":[{"index":0,"delta":{"content":"Explanation"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client: httpx.AsyncClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as client:
        model: ChatOpenAI = ChatOpenAI(
            model="scope",
            base_url="http://scope/v1",
            api_key="test",
            http_async_client=client,
            max_retries=0,
            stream_usage=False,
            http_socket_options=(),
        )
        adapter: LangChainLLM = LangChainLLM(model)
        chunks: AsyncIterator[Chunk]
        async with adapter.stream(messages) as chunks:
            assert "".join([chunk.text async for chunk in chunks]) == "Explanation"
    encoded_messages: list[dict[str, object]] = TypeAdapter(
        list[dict[str, object]]
    ).validate_python(requests[0]["messages"])
    encoded_user: dict[str, object] = next(
        item for item in encoded_messages if item["role"] == "user"
    )
    return TypeAdapter(dict[str, object]).validate_json(
        TypeAdapter(str).validate_python(encoded_user["content"])
    )

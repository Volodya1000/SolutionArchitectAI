from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend.test_helpers.sql_store_setup import (
    SqlStoreSetup,
)
from solution_architect_ai.application.models.clarification_models import (
    AnswerClarification,
    ClarificationQuestion,
    SourceVersion,
)
from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
    UploadDocument,
)
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionStart,
    ExtractionView,
    RequirementView,
    SourceRef,
    StoredModelProfile,
)
from solution_architect_ai.application.services.discussion_service import DiscussionService
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.di.main import bootstrap
from solution_architect_ai.domain.documents import ParsedDocument
from solution_architect_ai.domain.requirements import RequirementCategory
from solution_architect_ai.domain.runs import RunStatus
from solution_architect_ai.persistence.clarifications.clarification_store import (
    SqlAlchemyClarificationStore,
)
from solution_architect_ai.persistence.discussions.store import SqlAlchemyDiscussionStore
from solution_architect_ai.persistence.extractions.extraction_models import ExtractionRow
from solution_architect_ai.persistence.queries import DEFAULT_TASK_ID


@dataclass(frozen=True)
class Resources:
    discussions: DiscussionService
    stores: SqlStoreSetup[SqlAlchemyDiscussionStore]
    clarifications: SqlStoreSetup[SqlAlchemyClarificationStore]
    documents: DocumentService
    directory: Path


async def content_chunks(content: bytes) -> AsyncGenerator[bytes]:
    yield content


async def upload(resources: Resources, file_id: UUID | None = None) -> DocumentVersionView:
    return await resources.documents.upload(
        UploadDocument(
            operation_id=uuid4(),
            filename="requirements.md",
            mime_type="text/markdown",
            file_id=file_id,
        ),
        content_chunks(
            b"# Reporting\n\nR03 Reports must be published.\n\n"
            b"R04 Reports contain a comparison to the previous period.\n"
        ),
    )


async def seed_analysis(
    resources: Resources,
    version: DocumentVersionView,
    answer: str | None,
) -> tuple[UUID, UUID]:
    parsed: ParsedDocument = await resources.documents.get_parsed_document(version.version_id)
    source: SourceRef = await resources.discussions.source_reference(
        version.version_id, parsed.fragments[0].fragment_id
    )
    run_id: UUID = uuid4()
    requirement_id: UUID = uuid4()
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid4(), version_ids=[version.version_id], answer_history_mode="new"
    )
    settings: Settings = bootstrap()
    view: ExtractionView = ExtractionView(
        id=run_id,
        status=RunStatus.COMPLETED,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model="fake-chat",
        version_ids=[version.version_id],
        coverage=CoverageView(),
        model_profile=StoredModelProfile.model_validate(
            settings.llm.model_dump(mode="json", exclude={"api_key"})
        ),
        contract_version="test",
        prompt_version="test",
        requirements=[
            RequirementView(
                id=requirement_id,
                category=RequirementCategory.FUNCTIONAL,
                original_text="R03 Reports must be published.",
                normalized_text="R03 Reports must be published.",
                sources=[source],
            )
        ],
    )
    store: SqlAlchemyClarificationStore
    async with resources.clarifications.open() as store:
        store.session.add(
            ExtractionRow(
                id=run_id,
                task_id=DEFAULT_TASK_ID,
                operation_id=command.operation_id,
                payload_digest="test",
                config_digest="test",
                command_json=command.model_dump_json(),
                snapshot_json=view.model_dump_json(),
                status=view.status.value,
                created_at=view.created_at,
            )
        )
        await store.session.flush()
        if answer is not None:
            question: ClarificationQuestion = ClarificationQuestion(
                id=uuid4(),
                gap_key=f"report:{run_id}",
                text="How often?",
                basis="Not specified",
                dependent_decision="Report schedule",
                blocking=True,
                requirement_ids=[requirement_id],
                sources=[source],
            )
            await store.save_questions(run_id, [question])
            await store.answer(
                run_id,
                question.id,
                AnswerClarification(
                    operation_id=uuid4(),
                    expected_question_revision=1,
                    source_versions=[
                        SourceVersion(version_id=version.version_id, sha256=version.sha256)
                    ],
                    kind="answer",
                    text=answer,
                    basis="Architect decision",
                ),
            )
    return run_id, requirement_id

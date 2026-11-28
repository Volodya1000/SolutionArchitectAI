from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from dishka import AsyncContainer

from solution_architect_ai.application.models.document_dto import (
    DocumentVersionView,
    UploadDocument,
)
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.application.protocols.extraction_protocols import (
    ExtractionStore,
)
from solution_architect_ai.application.protocols.store_context_protocols import StoreContext
from solution_architect_ai.application.services.document_service import DocumentService
from solution_architect_ai.application.services.requirements_extraction_service import (
    RequirementsExtractionService,
)
from solution_architect_ai.config.settings import Settings
from solution_architect_ai.domain.runs import RunStatus

ORIGINAL: Final[str] = "\n".join(
    ("# Отчётность", "", "## Требования", "Система должна сохранять отчёты.", "")
)


@dataclass
class ExtractionResources:
    container: AsyncContainer
    settings: Settings
    documents: DocumentService
    stores: StoreContext[ExtractionStore]
    service: RequirementsExtractionService
    runs: list[UUID]

    async def start(self, versions: list[UUID], scope: str = "") -> ExtractionView:
        view: ExtractionView = await self.service.start(
            ExtractionStart(operation_id=uuid4(), version_ids=versions, analysis_scope=scope)
        )
        self.runs.append(view.id)
        return view

    async def view(self, run_id: UUID) -> ExtractionView:
        return await self.service.get(run_id)

    async def running(self, run_id: UUID) -> None:
        store: ExtractionStore
        async with self.stores.open() as store:
            await store.set_status(run_id, RunStatus.RUNNING)


async def upload(
    resources: ExtractionResources, text: str = ORIGINAL, file_id: UUID | None = None
) -> DocumentVersionView:
    async def chunks() -> AsyncGenerator[bytes]:
        yield text.encode()

    return await resources.documents.upload(
        UploadDocument(
            operation_id=uuid4(), filename="BRD.md", mime_type="text/markdown", file_id=file_id
        ),
        chunks(),
    )

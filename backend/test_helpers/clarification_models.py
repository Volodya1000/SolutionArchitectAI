from uuid import uuid4

from pydantic import BaseModel

from solution_architect_ai.application.models.extraction_models import (
    LocatorView,
    RequirementView,
    SourceRef,
)
from solution_architect_ai.application.models.structured_models import (
    StructuredRequest,
    StructuredResponse,
)
from solution_architect_ai.domain.documents import (
    DocumentFragment,
    ParsedDocument,
)
from solution_architect_ai.domain.requirements import EvidenceStatus, RequirementCategory


class ClarificationModel:
    def __init__(self, payload: str) -> None:
        self.payload: str = payload
        self.requests: list[StructuredRequest] = []

    async def invoke[T: BaseModel](
        self, request: StructuredRequest, _schema: type[T]
    ) -> StructuredResponse[T]:
        self.requests.append(request)
        return StructuredResponse(self.payload, "stop")


def referenced_requirement(document: ParsedDocument, fragment: DocumentFragment) -> RequirementView:
    return RequirementView(
        id=uuid4(),
        category=RequirementCategory.FUNCTIONAL,
        original_text=fragment.text,
        normalized_text=fragment.text,
        sources=[
            SourceRef(
                file_id=document.file_id,
                version_id=document.version_id,
                sha256=document.sha256,
                fragment_id=str(fragment.fragment_id),
                quote=fragment.text,
                status=EvidenceStatus.VERIFIED,
                reason=None,
                locator=LocatorView(
                    kind=fragment.locator.kind.value,
                    start=fragment.locator.start,
                    end=fragment.locator.end,
                    section=fragment.locator.section,
                    path=fragment.locator.path,
                ),
            )
        ],
    )

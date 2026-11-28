import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest

from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    CoverageView,
    ExtractionProgress,
    ExtractionView,
    StoredModelProfile,
)
from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.domain.runs import RunStatus
from tools.clarification_smoke import ClarificationSmoke, analyze

pytestmark: Final[pytest.MarkDecorator] = pytest.mark.anyio


@pytest.mark.parametrize("status", [RunStatus.WAITING_INPUT, RunStatus.COMPLETED])
async def test_smoke_uses_one_version_and_fresh_history_and_stops_for_human(
    tmp_path: Path, status: RunStatus
) -> None:
    run_id: UUID = uuid4()
    source: Path = tmp_path / "input.md"
    content: bytes = "Система хранит сведения.".encode()
    await asyncio.to_thread(source.write_bytes, content)
    version: DocumentVersionView = DocumentVersionView(
        file_id=uuid4(),
        version_id=uuid4(),
        task_id=uuid4(),
        sha256="a" * 64,
        mime_type="text/markdown",
        size=len(content),
        original_name=source.name,
        uploaded_at=datetime.now(UTC),
        storage_key="test",
    )
    profile: StoredModelProfile = StoredModelProfile.model_validate(
        LLMSettings().model_dump(mode="json", exclude={"api_key"})
    )
    extraction: ExtractionView = ExtractionView(
        id=run_id,
        status=status,
        progress=ExtractionProgress(),
        error_code=None,
        created_at=datetime.now(UTC),
        model=profile.model,
        model_profile=profile,
        coverage=CoverageView(),
        requirements=[],
        contract_version="test",
        prompt_version="test",
    )
    posted: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/documents":
            return httpx.Response(201, content=version.model_dump_json())
        if request.url.path == "/api/extractions":
            posted.append(json.loads(request.content))
        if request.url.path.endswith("/clarifications"):
            return httpx.Response(
                200, content=ClarificationView(run_id=run_id, history_id=run_id).model_dump_json()
            )
        return httpx.Response(200, content=extraction.model_dump_json())

    client: httpx.AsyncClient
    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(handle)
    ) as client:
        result: ClarificationSmoke = await analyze(client, source, uuid4(), 2)
    assert result.extraction.status == status
    assert posted[0]["answer_history_mode"] == "new"
    assert posted[0]["version_ids"] == [str(version.version_id)]
    assert result.source_sha256 != ""

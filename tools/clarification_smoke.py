"""Run one selected input with a fresh answer history through the local application."""

import argparse
import asyncio
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

import httpx

from solution_architect_ai.application.models.chat_dto import DTO
from solution_architect_ai.application.models.clarification_models import ClarificationView
from solution_architect_ai.application.models.document_dto import DocumentVersionView
from solution_architect_ai.application.models.extraction_models import (
    ExtractionStart,
    ExtractionView,
)
from solution_architect_ai.domain.runs import RunStatus
from tools.extraction_smoke import MIME_TYPES


class ClarificationSmoke(DTO):
    operation_id: UUID
    source_sha256: str
    version_id: UUID
    extraction: ExtractionView
    clarifications: ClarificationView


async def poll_actionable(client: httpx.AsyncClient, run_id: UUID) -> ExtractionView:
    while True:
        response: httpx.Response = await client.get(f"/api/extractions/{run_id}")
        response.raise_for_status()
        view: ExtractionView = ExtractionView.model_validate_json(response.content, strict=True)
        if view.status.terminal or view.status == RunStatus.WAITING_INPUT:
            return view
        await asyncio.sleep(0.5)


async def analyze(
    client: httpx.AsyncClient, source: Path, operation_id: UUID, time_limit: float
) -> ClarificationSmoke:
    content: bytes = await asyncio.to_thread(source.read_bytes)
    response: httpx.Response = await client.post(
        "/api/documents",
        params={
            "operation_id": str(uuid5(operation_id, "upload")),
            "filename": source.name,
        },
        content=content,
        headers={"Content-Type": MIME_TYPES[source.suffix.lower()]},
    )
    response.raise_for_status()
    version: DocumentVersionView = DocumentVersionView.model_validate_json(
        response.content, strict=True
    )
    command: ExtractionStart = ExtractionStart(
        operation_id=uuid5(operation_id, "extract"),
        version_ids=[version.version_id],
        answer_history_mode="new",
    )
    started: httpx.Response = await client.post(
        "/api/extractions",
        content=command.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    started.raise_for_status()
    run: ExtractionView = ExtractionView.model_validate_json(started.content, strict=True)
    print(
        f"operation_id={operation_id} run_id={run.id} version_id={version.version_id}", flush=True
    )
    async with asyncio.timeout(time_limit):
        result: ExtractionView = await poll_actionable(client, run.id)
    questions_response: httpx.Response = await client.get(
        f"/api/extractions/{run.id}/clarifications"
    )
    questions_response.raise_for_status()
    return ClarificationSmoke(
        operation_id=operation_id,
        source_sha256=sha256(content).hexdigest(),
        version_id=version.version_id,
        extraction=result,
        clarifications=ClarificationView.model_validate_json(
            questions_response.content, strict=True
        ),
    )


async def execute(
    base_url: str, source: Path, operation_id: UUID, time_limit: float
) -> ClarificationSmoke:
    client: httpx.AsyncClient
    async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=120) as client:
        return await analyze(client, source, operation_id, time_limit)


def main() -> None:
    arguments: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--base-url", default="http://127.0.0.1:8080")
    arguments.add_argument("--source", type=Path, required=True)
    arguments.add_argument("--output", type=Path, required=True)
    arguments.add_argument("--operation-id", type=UUID, default=uuid4())
    arguments.add_argument("--timeout", type=float, default=1800)
    options: argparse.Namespace = arguments.parse_args()
    if urlsplit(options.base_url).hostname not in {"localhost", "127.0.0.1"}:
        arguments.error("Use a local application endpoint")
    if (
        options.source.suffix.lower() not in MIME_TYPES
        or options.source.stat().st_size > 20 * 1024 * 1024
    ):
        arguments.error("Unsupported source or source exceeds 20 MiB")
    result: ClarificationSmoke = asyncio.run(
        execute(options.base_url, options.source, options.operation_id, options.timeout),
        loop_factory=asyncio.SelectorEventLoop,
    )
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"status={result.extraction.status} questions={len(result.clarifications.questions)} error={result.extraction.error_code}"
    )
    if result.extraction.status not in {RunStatus.COMPLETED, RunStatus.WAITING_INPUT}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

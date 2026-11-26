import argparse
import asyncio
import json
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

import httpx

from solution_architect_ai.application.document_dto import DocumentVersionView
from solution_architect_ai.application.extraction_models import ExtractionView
from solution_architect_ai.domain.runs import RunStatus

MIME_TYPES: Final[dict[str, str]] = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def poll(client: httpx.AsyncClient, run_id: UUID) -> ExtractionView:
    completed: int = -1
    while True:
        response: httpx.Response = await client.get(f"/api/extractions/{run_id}")
        response.raise_for_status()
        view: ExtractionView = ExtractionView.model_validate_json(response.content, strict=True)
        if view.progress.completed_parts != completed:
            completed = view.progress.completed_parts
            print(
                f"run={view.id} parts={completed}/{view.progress.total_parts} requests={view.requests}",
                flush=True,
            )
        if view.status.terminal:
            return view
        await asyncio.sleep(0.25)


async def execute(
    base_url: str, source: Path, operation_id: UUID, time_limit: float
) -> ExtractionView:
    content: bytes = await asyncio.to_thread(source.read_bytes)
    async with httpx.AsyncClient(base_url=base_url, trust_env=False, timeout=120) as client:
        response: httpx.Response = await client.post(
            "/api/documents",
            params={"operation_id": str(uuid5(operation_id, "upload")), "filename": source.name},
            content=content,
            headers={"Content-Type": MIME_TYPES[source.suffix.lower()]},
        )
        response.raise_for_status()
        version: DocumentVersionView = DocumentVersionView.model_validate_json(
            response.content, strict=True
        )
        started: httpx.Response = await client.post(
            "/api/extractions",
            json={
                "operation_id": str(uuid5(operation_id, "extract")),
                "version_ids": [str(version.version_id)],
                "analysis_scope": "BRD",
            },
        )
        started.raise_for_status()
        run: ExtractionView = ExtractionView.model_validate_json(started.content, strict=True)
        try:
            async with asyncio.timeout(time_limit):
                return await poll(client, run.id)
        except (TimeoutError, asyncio.CancelledError):
            await client.post(f"/api/extractions/{run.id}/cancel")
            raise


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Local persisted extraction smoke; no direct LLM API calls"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operation-id", type=UUID, default=uuid4())
    parser.add_argument("--expected-model")
    parser.add_argument("--timeout", type=float, default=1800)
    args: argparse.Namespace = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Use a local application endpoint")
    if (
        args.source.suffix.lower() not in MIME_TYPES
        or args.source.stat().st_size > 20 * 1024 * 1024
    ):
        parser.error("Unsupported input or input exceeds 20 MiB")
    result: ExtractionView = asyncio.run(
        execute(args.base_url, args.source, args.operation_id, args.timeout),
        loop_factory=asyncio.SelectorEventLoop,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "run_id": str(result.id),
                "model": result.model,
                "status": result.status.value,
                "requirements": len(result.requirements),
                "requests": result.requests,
                "error": result.error_code,
            },
            ensure_ascii=False,
        )
    )
    if result.status != RunStatus.COMPLETED or (
        args.expected_model and result.model != args.expected_model
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

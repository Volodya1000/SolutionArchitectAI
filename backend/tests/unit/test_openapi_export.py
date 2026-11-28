import json
from pathlib import Path
from typing import Never

import pytest

from tools.export_openapi import export_openapi


def test_openapi_export_is_offline_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_runtime(*_args: object, **_kwargs: object) -> Never:
        pytest.fail("OpenAPI export tried to start a database or LLM client")

    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", reject_runtime)
    monkeypatch.setattr("httpx.AsyncClient.__init__", reject_runtime)
    first: Path = tmp_path / "first.json"
    second: Path = tmp_path / "second.json"
    export_openapi(first)
    export_openapi(second)
    assert first.read_bytes() == second.read_bytes()
    content: str = first.read_text(encoding="utf-8")
    assert '"ClarificationView"' in content
    assert '"ExtractionPipelineVersions"' in content
    assert '"RunSnapshotEvent"' in content
    assert '"text/event-stream"' in content
    assert '"format": "binary"' in content
    schema: dict[str, object] = json.loads(content)
    components: object = schema["components"]
    assert isinstance(components, dict)
    definitions: object = components["schemas"]
    assert isinstance(definitions, dict)
    clarification: object = definitions["ClarificationView"]
    assert isinstance(clarification, dict)
    required: object = clarification["required"]
    assert isinstance(required, list)
    assert "questions" in required

from pathlib import Path
from typing import Any

import pytest

from solution_architect_ai.di import server


@pytest.mark.parametrize("host", [None, "127.0.0.1"])
def test_container_entrypoint_defaults_to_reachable_host_and_honors_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str | None
) -> None:
    from solution_architect_ai.di import container

    monkeypatch.setenv("SAA_CONFIG_ROOT", str(tmp_path))
    monkeypatch.setenv("SAA_SERVER__PORT", "8200")
    monkeypatch.delenv("SAA_SERVER__HOST", raising=False)
    if host is not None:
        monkeypatch.setenv("SAA_SERVER__HOST", host)
    options: dict[str, Any] = {}

    def launch(_app: str, **kwargs: Any) -> None:
        options.update(kwargs)

    monkeypatch.setattr(server.uvicorn, "run", launch)
    container.main()
    assert options["host"] == (host or "0.0.0.0")
    assert options["port"] == 8200
    assert options["factory"] is True
    assert options["workers"] == 1

from pathlib import Path
from typing import Final, TypedDict, Unpack

import pytest
import uvicorn

from solution_architect_ai.di import container

# Uvicorn is replaced with a callback, so the expected host never opens a socket.
BIND_ALL_HOST: Final[str] = "0.0.0.0"  # nosec B104


class LaunchOptions(TypedDict):
    factory: bool
    host: str
    port: int
    workers: int
    timeout_graceful_shutdown: int


@pytest.mark.parametrize("host", [None, "127.0.0.1"])
def test_container_entrypoint_defaults_to_reachable_host_and_honors_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str | None
) -> None:
    monkeypatch.setenv("SAA_CONFIG_ROOT", str(tmp_path))
    monkeypatch.setenv("SAA_SERVER__PORT", "8200")
    monkeypatch.delenv("SAA_SERVER__HOST", raising=False)
    if host is not None:
        monkeypatch.setenv("SAA_SERVER__HOST", host)
    launches: list[LaunchOptions] = []

    def launch(_app: str, **kwargs: Unpack[LaunchOptions]) -> None:
        launches.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", launch)
    container.main()
    assert len(launches) == 1
    options: LaunchOptions = launches[0]
    assert options["host"] == (host or BIND_ALL_HOST)
    assert options["port"] == 8200
    assert options["factory"] is True
    assert options["workers"] == 1

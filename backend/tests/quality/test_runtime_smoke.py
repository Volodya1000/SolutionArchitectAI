import runpy
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Never

import pytest

from tools import quality_runtime, runtime_smoke
from tools.quality_runtime import RuntimeEnvironment


def test_fault_command_requires_an_isolated_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAA_QUALITY_PROJECT", raising=False)

    def unexpected_docker(*_arguments: str) -> Never:
        pytest.fail("Invoked Docker without an isolated project")

    monkeypatch.setattr(runtime_smoke, "docker", unexpected_docker)
    with pytest.raises(ValueError, match="SAA_QUALITY_PROJECT"):
        runtime_smoke.compose("stop", "postgres")


def test_url_mismatch_blocks_fault_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAA_QUALITY_PROJECT", "saa-quality-test")
    monkeypatch.setattr(runtime_smoke, "BASE", "http://127.0.0.1:8801")
    calls: list[tuple[str, ...]] = []

    def record_docker(*arguments: str) -> str:
        calls.append(arguments)
        assert arguments[-3:] == ("port", "frontend", "8080")
        return "127.0.0.1:8802"

    def unexpected_api(*_arguments: object, **_options: object) -> Never:
        pytest.fail("Contacted the application before validating the isolated URL")

    monkeypatch.setattr(runtime_smoke, "docker", record_docker)
    monkeypatch.setattr(runtime_smoke, "api", unexpected_api)
    with pytest.raises(ValueError, match="SAA_APP_URL"):
        runtime_smoke.run_smoke()
    assert calls == [
        (
            *quality_runtime.compose_command(runtime_smoke.ROOT, "saa-quality-test")[1:],
            "port",
            "frontend",
            "8080",
        ),
    ]


def test_standalone_starts_child_in_disposable_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAA_QUALITY_PROJECT", raising=False)
    monkeypatch.setenv("SAA_APP_URL", "http://127.0.0.1:8080")
    browser: dict[str, str] = {
        "SAA_QUALITY_PROJECT": "saa-quality-child",
        "SAA_APP_URL": "http://127.0.0.1:8802",
        "SAA_LLM__MODEL": "fake-chat",
    }
    actions: list[str] = []

    @contextmanager
    def isolated(root: Path) -> Iterator[RuntimeEnvironment]:
        assert root == runtime_smoke.ROOT
        actions.append("start")
        try:
            yield RuntimeEnvironment(backend={}, browser=browser)
        finally:
            actions.append("stop")

    def record_child(
        arguments: list[str], *, cwd: Path, env: dict[str, str], check: bool, timeout: int
    ) -> None:
        assert arguments == [sys.executable, "-m", "tools.runtime_smoke"]
        assert cwd == runtime_smoke.ROOT
        assert env == browser
        assert check
        assert timeout > 0
        actions.append("child")

    def unexpected_request(*_arguments: object, **_options: object) -> Never:
        pytest.fail("Standalone smoke contacted the developer's configured URL")

    monkeypatch.setattr(quality_runtime, "isolated_runtime", isolated)
    monkeypatch.setattr("subprocess.run", record_child)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", unexpected_request)
    runpy.run_path(str(runtime_smoke.ROOT / "tools/runtime_smoke.py"), run_name="__main__")
    assert actions == ["start", "child", "stop"]

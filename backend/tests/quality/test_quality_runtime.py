from pathlib import Path
from subprocess import CompletedProcess  # nosec B404
from unittest.mock import Mock

import pytest

from tools import quality_runtime
from tools.quality_runtime import RuntimeEnvironment, compose_command, runtime_environment


def test_quality_environment_cannot_inherit_the_developers_model_or_published_ports() -> None:
    original: dict[str, str] = {
        "PATH": "tool-path",
        "SAA_LLM__BASE_URL": "http://real-model:1234/v1",
        "SAA_LLM__MODEL": "real-model",
        "SAA_LLM__API_KEY": "must-not-enter-test-runtime",
        "COMPOSE_FRONTEND_PORT": "8080",
        "COMPOSE_PROJECT_NAME": "developer-app",
        "PLAYWRIGHT_CHANNEL": "msedge",
    }
    result: dict[str, str] = runtime_environment(original)
    assert result["SAA_LLM__BASE_URL"] == "http://fake-llm:8000/v1"
    assert result["SAA_LLM__MODEL"] == "fake-chat"
    assert result["COMPOSE_FRONTEND_PORT"] == "0"
    assert result["COMPOSE_POSTGRES_PORT"] == "0"
    assert "COMPOSE_PROJECT_NAME" not in result
    assert result["SAA_LLM__API_KEY"] == "local-no-external-key"
    assert result["PLAYWRIGHT_CHANNEL"] == "msedge"
    assert result["PATH"] == "tool-path"
    assert original["SAA_LLM__MODEL"] == "real-model"


def test_compose_cleanup_is_always_scoped_and_ignores_the_local_dotenv(tmp_path: Path) -> None:
    command: list[str] = compose_command(tmp_path, "saa-quality-example")
    assert command[:4] == ["docker", "compose", "--project-name", "saa-quality-example"]
    assert command[command.index("--env-file") + 1] == str(tmp_path / ".env.quality")
    assert command[command.index("--file") + 1] == str(tmp_path / "docker-compose.yml")


def test_backend_config_root_only_exposes_the_project_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project: str = "saa-quality-example"
    directory: Path = tmp_path / ".build" / project
    directory.mkdir(parents=True)
    source: Path = tmp_path / "config/app.yaml"
    source.parent.mkdir()
    source.write_bytes(b"llm:\n  output_limit: 192\n")
    (source.parent / "private.yaml").touch()
    (tmp_path / ".env.test").touch()
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/SAA_LLM__API_KEY").touch()
    monkeypatch.setattr(quality_runtime, "published_port", Mock(return_value="12345"))
    runtime: RuntimeEnvironment = quality_runtime.service_environments(
        tmp_path, compose_command(tmp_path, project), {}, directory, project
    )
    config_root: Path = Path(runtime.backend["SAA_CONFIG_ROOT"])
    assert config_root.is_relative_to(directory)
    assert {path.relative_to(config_root).as_posix() for path in config_root.rglob("*")} == {
        "config",
        "config/app.yaml",
    }
    assert (config_root / "config/app.yaml").read_bytes() == source.read_bytes()


def test_cleanup_removes_only_the_scoped_projects_local_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command: list[str] = compose_command(tmp_path, "saa-quality-example")
    result: CompletedProcess[str] = CompletedProcess(command, 0, stdout="", stderr="")
    docker: Mock = Mock(return_value=result)
    monkeypatch.setattr(quality_runtime, "compose", docker)
    quality_runtime.cleanup_runtime(tmp_path, command, {}, tmp_path, failed=False)
    docker.assert_called_with(
        tmp_path,
        [*command, "down", "--volumes", "--remove-orphans", "--rmi", "local"],
        {},
        check=False,
    )

from pathlib import Path

from tools.quality_runtime import compose_command, runtime_environment


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

import traceback
from pathlib import Path
from typing import Final

import pytest
from pydantic import SecretStr

from solution_architect_ai.config.models import LLMSettings
from solution_architect_ai.config.settings import Settings, load_settings

BIND_ALL_HOST: Final[str] = "0.0.0.0"  # nosec B104


def test_nested_env_overrides_yaml_without_reading_developer_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text(
        "llm:\n  model: yaml-model\n  output_limit: 80\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("SAA_LLM__MODEL=developer-model\n", encoding="utf-8")
    monkeypatch.setenv("SAA_LLM__OUTPUT_LIMIT", "120")
    settings: Settings = load_settings(tmp_path, "test")
    assert settings.llm.model == "yaml-model"
    assert settings.llm.output_limit == 120


@pytest.mark.parametrize(
    "source",
    [
        "llm:\n  model: first\n  model: second\n",
        "llm:\n  unknown_parameter: 1\n",
        "llm:\n  api_key: secret-must-not-leak\n",
        "llm: !!python/object:object {}\n",
    ],
)
def test_invalid_or_secret_yaml_is_rejected_without_exposing_values(
    tmp_path: Path, source: str
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text(source, encoding="utf-8")
    error: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "test")
    assert "secret-must-not-leak" not in str(error.value)


def test_unknown_prefixed_env_does_not_hide_typo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAA_LLM__MODLE", "bad")
    with pytest.raises(ValueError, match=r".+"):
        load_settings(tmp_path, "test")


def test_nested_secret_file_is_loaded_and_conflicting_env_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_dir: Path = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "SAA_DATABASE__CREDENTIALS__PASSWORD").write_text(
        "test-secret-only", encoding="utf-8"
    )
    settings: Settings = load_settings(tmp_path, "production")
    assert settings.database.credentials.password.get_secret_value() == "test-secret-only"
    monkeypatch.setenv("SAA_DATABASE__CREDENTIALS__PASSWORD", "another-secret")
    error: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "production")
    assert "another-secret" not in str(error.value)


def test_invalid_yaml_traceback_does_not_expose_values(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text("llm: [secret-trace-value\n", encoding="utf-8")
    error: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "production")
    trace: str = "".join(traceback.format_exception(error.value))
    assert "secret-trace-value" not in trace


def test_production_rejects_secrets_from_init(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r".+"):
        Settings(
            config_root=tmp_path,
            mode="production",
            llm=LLMSettings(api_key=SecretStr("test-only")),
        )


def test_dotenv_cannot_duplicate_a_mounted_secret(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/SAA_LLM__API_KEY").write_text("file-secret", encoding="utf-8")
    (tmp_path / ".env").write_text("SAA_LLM__API_KEY=dotenv-secret", encoding="utf-8")
    with pytest.raises(ValueError, match=r".+"):
        load_settings(tmp_path, "development")


def test_malformed_env_traceback_does_not_expose_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAA_LLM", "[secret-env-trace")
    error: pytest.ExceptionInfo[ValueError]
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "production")
    assert "secret-env-trace" not in "".join(traceback.format_exception(error.value))


def test_server_listener_environment_overrides_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text(
        "server:\n  host: 127.0.0.1\n  port: 8100\n", encoding="utf-8"
    )
    monkeypatch.setenv("SAA_SERVER__HOST", BIND_ALL_HOST)
    monkeypatch.setenv("SAA_SERVER__PORT", "8200")
    settings: Settings = load_settings(tmp_path, "test")
    assert settings.server.host == BIND_ALL_HOST
    assert settings.server.port == 8200


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_server_port_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("SAA_SERVER__PORT", port)
    with pytest.raises(ValueError, match=r".+"):
        load_settings(tmp_path, "test")

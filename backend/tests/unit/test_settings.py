import traceback
from pathlib import Path

import pytest

from solution_architect_ai.config.settings import Settings, load_settings


def test_nested_env_overrides_yaml_without_reading_developer_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text(
        "llm:\n  model: yaml-model\n  output_limit: 80\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("SAA_LLM__MODEL=developer-model\n", encoding="utf-8")
    monkeypatch.setenv("SAA_LLM__OUTPUT_LIMIT", "120")
    settings = load_settings(tmp_path, "test")
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
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "SAA_DATABASE__CREDENTIALS__PASSWORD").write_text(
        "test-secret-only", encoding="utf-8"
    )
    settings = load_settings(tmp_path, "production")
    assert settings.database.credentials.password.get_secret_value() == "test-secret-only"
    monkeypatch.setenv("SAA_DATABASE__CREDENTIALS__PASSWORD", "another-secret")
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "production")
    assert "another-secret" not in str(error.value)


def test_invalid_yaml_traceback_does_not_expose_values(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.yaml").write_text("llm: [secret-trace-value\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r".+") as error:
        load_settings(tmp_path, "production")
    trace = "".join(traceback.format_exception(error.value))
    assert "secret-trace-value" not in trace


def test_production_rejects_secrets_from_init(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r".+"):
        Settings(config_root=tmp_path, mode="production", llm={"api_key": "test-only"})

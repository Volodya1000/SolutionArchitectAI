from pathlib import Path
from typing import ClassVar

from pydantic import Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    NestedSecretsSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import InitSettingsSource

from solution_architect_ai.config.models import (
    DatabaseSettings,
    GitSettings,
    LLMSettings,
    Mode,
    ServerSettings,
    StorageSettings,
)
from solution_architect_ai.config.sources import (
    contains_secret_override,
    read_yaml,
    validate_environment,
    validate_keys,
    validate_secret_directory,
)


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="SAA_", env_nested_delimiter="__", extra="forbid", hide_input_in_errors=True
    )
    config_root: Path = Field(exclude=True)
    mode: Mode = Field(default="production", exclude=True)
    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    git: GitSettings = Field(default_factory=GitSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        initial: dict[str, object] = init_settings()
        if initial.get("mode", "production") == "production" and contains_secret_override(initial):
            raise ValueError("Production secrets cannot be supplied through init overrides")
        root: Path = Path(str(initial.get("config_root", ".")))
        data: dict[str, object] = read_yaml(root / "config/app.yaml")
        validate_keys(data, cls)
        secret_dir: Path = root / "secrets"
        secrets: tuple[PydanticBaseSettingsSource, ...] = ()
        if secret_dir.exists():
            validate_secret_directory(secret_dir, env_settings(), dotenv_settings())
            secrets = (
                NestedSecretsSettingsSource(
                    file_secret_settings,
                    secrets_dir=secret_dir,
                    secrets_prefix="SAA_",
                    secrets_nested_delimiter="__",
                ),
            )
        return (
            init_settings,
            *secrets,
            env_settings,
            dotenv_settings,
            InitSettingsSource(settings_cls, data),
        )


def load_settings(root: Path, mode: Mode) -> Settings:
    validate_environment(Settings)
    dotenv: str | None = {"development": ".env", "test": ".env.test"}.get(mode)
    try:
        return Settings(
            config_root=root.resolve(), mode=mode, _env_file=root / dotenv if dotenv else None
        )
    except ValidationError as error:
        locations: list[str] = [
            ".".join(str(part) for part in item["loc"]) for item in error.errors()
        ]
        raise ValueError("Invalid configuration fields: " + ", ".join(locations)) from None

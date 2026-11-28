from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Section(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", hide_input_in_errors=True, allow_inf_nan=False
    )


class ServerSettings(Section):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)


class LocalActorSettings(Section):
    id: UUID = UUID("10000000-0000-4000-8000-000000000003")
    name: str = Field(default="Локальный архитектор", min_length=1, max_length=120)
    can_write: bool = True


class DatabaseCredentials(Section):
    password: SecretStr = Field(default=SecretStr("local-development-only"), repr=False)


class DatabaseSettings(Section):
    host: str = "postgres"
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = "solution_architect"
    database: str = "solution_architect"
    credentials: DatabaseCredentials = Field(default_factory=DatabaseCredentials)


class RetryConfig(Section):
    network_retries: int = Field(default=1, ge=0, le=3)
    validation_retries: int = Field(default=1, ge=0, le=3)
    max_total_requests: int = Field(default=2, ge=1, le=256)
    deadline_seconds: float = Field(default=120, gt=0, le=3600)
    request_timeout_seconds: float = Field(default=60, gt=0, le=600)
    backoff_initial: float = Field(default=0.25, ge=0)
    backoff_max: float = Field(default=2, ge=0)
    jitter: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def validate_budget(self) -> "RetryConfig":
        if self.request_timeout_seconds > self.deadline_seconds:
            raise ValueError("request timeout exceeds deadline")
        if self.backoff_initial > self.backoff_max:
            raise ValueError("initial backoff exceeds maximum")
        return self


class LLMSettings(Section):
    base_url: str = "http://fake-llm:8000/v1"
    model: str = "fake-chat"
    api_key: SecretStr | None = Field(default=None, repr=False)
    context_window: int = Field(default=4096, ge=512)
    output_limit: int = Field(default=512, ge=1)
    temperature: float = Field(default=0.2, ge=0, le=2)
    approximate_chars_per_token: float = Field(default=1, gt=0, le=4)
    concurrency: int = Field(default=1, ge=1, le=4)
    structured_mode: Literal["native_json_schema", "json_text"] = "json_text"
    service_tokens: int = Field(default=256, ge=0, le=4096)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @model_validator(mode="after")
    def validate_profile(self) -> "LLMSettings":
        url: SplitResult = urlsplit(self.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("LLM endpoint must be an HTTP URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("LLM URL cannot contain credentials, query or fragment")
        if self.output_limit >= self.context_window:
            raise ValueError("output limit leaves no input budget")
        return self


class StorageSettings(Section):
    root: Path = Path("/data/files")


class GitSettings(Section):
    root: Path = Path("/data/git")


type Mode = Literal["development", "test", "production"]

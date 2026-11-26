"""Run acceptance checks without touching the developer's Compose project or model."""

import os
import re

# Only scoped Docker commands are executed, with explicit argument vectors.
import subprocess  # nosec B404
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

# Internal container binding; published ports are always loopback.
CONTAINER_HOST: Final[str] = "0.0.0.0"  # nosec B104

PORT_VARIABLES: Final[tuple[str, ...]] = (
    "COMPOSE_BACKEND_PORT",
    "COMPOSE_FRONTEND_PORT",
    "COMPOSE_POSTGRES_PORT",
    "COMPOSE_FAKE_LLM_PORT",
)


@dataclass(frozen=True)
class RuntimeEnvironment:
    backend: dict[str, str]
    browser: dict[str, str]


def runtime_environment(original: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {
        key: value for key, value in original.items() if not key.startswith(("SAA_", "COMPOSE_"))
    }
    result.update(
        {
            "SAA_LLM__BASE_URL": "http://fake-llm:8000/v1",
            "SAA_LLM__MODEL": "fake-chat",
            "SAA_LLM__API_KEY": "local-no-external-key",
            "SAA_DATABASE__CREDENTIALS__PASSWORD": uuid4().hex,
            "SAA_SERVER__HOST": CONTAINER_HOST,
            "SAA_SERVER__PORT": "8000",
            "COMPOSE_BIND_HOST": "127.0.0.1",
            "COMPOSE_FRONTEND_LISTEN_PORT": "8080",
            "PYTHONUTF8": "1",
        }
    )
    name: str
    for name in PORT_VARIABLES:
        result[name] = "0"  # Let Docker allocate free published ports atomically.
    return result


def compose_command(root: Path, project: str) -> list[str]:
    if re.fullmatch(r"saa-quality-[a-z0-9-]+", project) is None:
        raise ValueError("Quality cleanup requires an isolated project name")
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(root / ".env.quality"),
        "--file",
        str(root / "docker-compose.yml"),
    ]


def compose(
    root: Path,
    command: Sequence[str],
    env: Mapping[str, str],
    *,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        command,
        cwd=root,
        env=env,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        timeout=900,
    )


def published_port(
    root: Path, command: list[str], env: Mapping[str, str], service: str, port: int
) -> str:
    result: subprocess.CompletedProcess[str] = compose(
        root,
        [*command, "port", service, str(port)],
        env,
        capture=True,
    )
    address: str = result.stdout.strip()
    host: str
    published: str
    host, published = address.rsplit(":", 1)
    if host != "127.0.0.1" or not published.isdecimal():
        raise ValueError("Quality service must publish a loopback port")
    return published


def service_environments(
    root: Path, command: list[str], env: dict[str, str], directory: Path, project: str
) -> RuntimeEnvironment:
    backend: dict[str, str] = dict(env)
    backend.update(
        {
            "SAA_MODE": "test",
            "SAA_CONFIG_ROOT": str(root),
            "SAA_DATABASE__HOST": "127.0.0.1",
            "SAA_DATABASE__PORT": published_port(root, command, env, "postgres", 5432),
            "SAA_DATABASE__DATABASE": "solution_architect_test",
            "SAA_LLM__BASE_URL": "http://127.0.0.1:"
            + published_port(root, command, env, "fake-llm", 8000)
            + "/v1",
            "SAA_GIT__ROOT": str(directory / "git"),
            "SAA_STORAGE__ROOT": str(directory / "files"),
        }
    )
    (directory / "git").mkdir()
    (directory / "files").mkdir()
    browser: dict[str, str] = dict(env)
    browser["SAA_APP_URL"] = "http://127.0.0.1:" + published_port(
        root, command, env, "frontend", 8080
    )
    # Runtime fault smoke must restart this same isolated project with the fake profile.
    browser["SAA_QUALITY_PROJECT"] = project
    return RuntimeEnvironment(backend=backend, browser=browser)


@contextmanager
def isolated_runtime(root: Path) -> Iterator[RuntimeEnvironment]:
    project: str = f"saa-quality-{uuid4().hex[:12]}"
    command: list[str] = compose_command(root, project)
    env: dict[str, str] = runtime_environment(os.environ)
    directory: Path = root / ".build" / "quality" / project
    directory.mkdir(parents=True)
    try:
        compose(root, [*command, "config", "--quiet"], env)
        compose(root, [*command, "up", "-d", "--build", "--wait", "--wait-timeout", "180"], env)
        compose(
            root,
            [
                *command,
                "exec",
                "-T",
                "postgres",
                "createdb",
                "-U",
                "solution_architect",
                "solution_architect_test",
            ],
            env,
        )
        yield service_environments(root, command, env, directory, project)
    finally:
        cleanup_runtime(root, command, env, directory, failed=sys.exc_info()[0] is not None)


def cleanup_runtime(
    root: Path, command: list[str], env: dict[str, str], directory: Path, *, failed: bool
) -> None:
    logs: subprocess.CompletedProcess[str] = compose(
        root, [*command, "logs", "--no-color"], env, capture=True, check=False
    )
    (directory / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
    cleanup: subprocess.CompletedProcess[str] = compose(
        root, [*command, "down", "--volumes", "--remove-orphans"], env, check=False
    )
    if cleanup.returncode and not failed:
        raise RuntimeError("Quality project cleanup failed; see compose.log")

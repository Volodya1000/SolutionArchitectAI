"""Exercise persistence, process interruption, SSE disconnect and database failure."""

import json
import os
import re
import shutil

# Launch the controlled Docker commands below.
import subprocess  # nosec B404
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO, Final
from uuid import UUID, uuid4

from solution_architect_ai.application.dto import (
    ChatSnapshot,
    ChatView,
    HealthStatus,
    ModelStatus,
    RunSnapshotEvent,
    RunView,
)

from solution_architect_ai.domain.runs import RunErrorCode, RunStatus

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
BASE: Final[str] = os.environ.get("SAA_APP_URL", "http://127.0.0.1:8080").rstrip("/")
HTTP: Final[urllib.request.OpenerDirector] = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)


def api(path: str, body: dict[str, str] | None = None) -> bytes:
    request: urllib.request.Request = urllib.request.Request(
        BASE + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    response: BinaryIO
    with HTTP.open(request, timeout=10) as response:
        return response.read()


def docker(*arguments: str) -> str:
    executable: str | None = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker is required for runtime smoke checks")
    # Arguments are defined by this script or are a container ID returned by Docker.
    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [executable, *arguments], cwd=ROOT, check=True, capture_output=True, text=True, timeout=120
    )
    return result.stdout.strip()


def compose(*arguments: str) -> str:
    project: str | None = os.environ.get("SAA_QUALITY_PROJECT")
    if project is None:
        return docker("compose", *arguments)
    if re.fullmatch(r"saa-quality-[a-z0-9-]+", project) is None:
        raise ValueError("Expected a dedicated saa-quality-* Compose project")
    return docker(
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(ROOT / ".env.quality"),
        "--file",
        str(ROOT / "docker-compose.yml"),
        *arguments,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def create_chat(title: str) -> UUID:
    return ChatView.model_validate_json(api("/chats", {"title": title}), strict=True).id


def read_run(run_id: UUID) -> RunView:
    return RunView.model_validate_json(api(f"/runs/{run_id}"), strict=True)


def await_run(run_id: UUID, *, terminal: bool = True) -> RunView:
    deadline: float = time.monotonic() + 20
    while time.monotonic() < deadline:
        run: RunView = read_run(run_id)
        if terminal and run.status.terminal:
            return run
        if not terminal and run.content:
            return run
        time.sleep(0.05)
    raise TimeoutError("Run did not reach the expected state")


def start(chat: UUID, content: str) -> UUID:
    run: RunView = RunView.model_validate_json(
        api(f"/chats/{chat}/runs", {"command_id": str(uuid4()), "content": content}),
        strict=True,
    )
    require(run.model == "fake-chat", "Runtime fault injection requires the fake-chat profile")
    return run.id


def stream_disconnect(chat: UUID) -> None:
    run_id: UUID = start(chat, "[slow] disconnect smoke")
    sequences: list[int] = []
    stream: BinaryIO
    raw: bytes
    with HTTP.open(BASE + f"/api/runs/{run_id}/events", timeout=10) as stream:
        for raw in stream:
            if not raw.startswith(b"data: "):
                continue
            event: RunSnapshotEvent = RunSnapshotEvent.model_validate_json(raw[6:], strict=True)
            sequences.append(event.sequence)
            if event.payload.content:
                break
    require(sequences == sorted(set(sequences)), "SSE event sequences were repeated or unordered")
    require(read_run(run_id).status == RunStatus.RUNNING, "SSE disconnect interrupted generation")
    api(f"/runs/{run_id}/cancel", {})
    require(
        await_run(run_id).status == RunStatus.CANCELLED, "The disconnected run was not cancelled"
    )


def graceful_shutdown() -> None:
    chat: UUID = create_chat("Штатная остановка SSE")
    run_id: UUID = start(chat, "[slow] graceful shutdown")
    partial: str = await_run(run_id, terminal=False).content
    stream: BinaryIO
    with HTTP.open(BASE + f"/api/runs/{run_id}/events", timeout=15) as stream:
        require(stream.readline().startswith(b"id:"), "Expected a snapshot from the SSE stream")
        started: float = time.monotonic()
        compose("stop", "backend")
        require(time.monotonic() - started < 15, "Backend exceeded its graceful shutdown timeout")
    container: str = compose("ps", "-aq", "backend")
    exit_code: str = docker("inspect", "-f", "{{.State.ExitCode}}", container)
    require(exit_code == "0", "Backend was forcibly killed instead of closing its resources")
    compose("up", "-d", "--wait", "backend")
    restored: RunView = read_run(run_id)
    require(restored.status == RunStatus.FAILED, "Shutdown did not fail the interrupted run")
    require(
        restored.error_code == RunErrorCode.PROCESS_INTERRUPTED,
        "Expected process interruption error",
    )
    require(restored.content.startswith(partial), "Shutdown lost partial output")


def abrupt_restart(chat: UUID) -> None:
    interrupted: UUID = start(chat, "[slow] abrupt restart")
    partial: str = await_run(interrupted, terminal=False).content
    compose("kill", "-s", "SIGKILL", "backend")
    compose("up", "-d", "--wait", "backend")
    restored: RunView = read_run(interrupted)
    require(restored.status == RunStatus.FAILED, "Restart did not fail the interrupted run")
    require(restored.incomplete is True, "The interrupted run was reported as complete")
    require(restored.content.startswith(partial), "Restart lost partial output")


def history(chat: UUID) -> ChatSnapshot:
    return ChatSnapshot.model_validate_json(api(f"/chats/{chat}"), strict=True)


def require_storage_unavailable(path: str) -> None:
    error: urllib.error.HTTPError
    try:
        api(path)
    except urllib.error.HTTPError as error:
        require(error.code == 503, f"{path} returned HTTP {error.code} instead of 503")
    else:
        raise AssertionError(f"{path} reported unavailable PostgreSQL as available")


def database_outage() -> None:
    try:
        compose("stop", "postgres")
        require_storage_unavailable("/health/ready")
        require_storage_unavailable("/chats")
    finally:
        compose("up", "-d", "--wait", "postgres")


def run_smoke() -> None:
    status: ModelStatus = ModelStatus.model_validate_json(api("/model"), strict=True)
    require(status.model == "fake-chat", "Runtime fault injection requires the fake-chat profile")
    first: UUID = create_chat("Проверка сохранности")
    second: UUID = create_chat("Независимый чат")
    run: UUID = start(first, "Проверка сохранения истории")
    require(await_run(run).status == RunStatus.COMPLETED, "The ordinary run did not complete")
    stream_disconnect(first)
    graceful_shutdown()
    abrupt_restart(first)
    compose("restart", "postgres")
    compose("up", "-d", "--wait", "postgres")
    require(not history(second).messages, "Messages appeared in an independent chat")
    require(len(history(first).messages) == 6, "Unexpected history length after PostgreSQL restart")
    database_outage()
    ready: HealthStatus = HealthStatus.model_validate_json(api("/health/ready"), strict=True)
    require(ready.status == "ready", "Backend did not become ready when PostgreSQL recovered")
    require(len(history(first).messages) == 6, "Unexpected history length after PostgreSQL outage")
    print(
        "Runtime smoke passed: SSE disconnect, cancellation, graceful shutdown, abrupt restart, "
        "PostgreSQL restart/outage, isolated history."
    )


if __name__ == "__main__":
    run_smoke()

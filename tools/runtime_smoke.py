"""Exercise persistence, process interruption, SSE disconnect and database failure."""
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8080"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    request = urllib.request.Request(BASE + "/api" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    with HTTP.open(request, timeout=10) as response:
        return json.load(response)


def compose(*arguments: str) -> None:
    subprocess.run(["docker", "compose", *arguments], cwd=ROOT, check=True,
        capture_output=True, timeout=120)


def await_run(run_id: str, *, terminal: bool = True) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        run = api("/runs/" + run_id)
        if terminal and run["status"] in {"completed", "failed", "cancelled"}:
            return run
        if not terminal and run["content"]:
            return run
        time.sleep(0.05)
    raise TimeoutError("Run did not reach the expected state")


def start(chat: str, content: str) -> str:
    run = api(f"/chats/{chat}/runs", {"command_id": str(uuid4()), "content": content})
    if run["model"] != "fake-chat":
        raise ValueError("Runtime fault injection requires the fake-chat profile")
    return str(run["id"])


def stream_disconnect(chat: str) -> None:
    run_id = start(chat, "[slow] disconnect smoke")
    sequences: list[int] = []
    with HTTP.open(BASE + f"/api/runs/{run_id}/events", timeout=10) as stream:
        for raw in stream:
            if not raw.startswith(b"data: "):
                continue
            event = json.loads(raw[6:])
            sequences.append(event["sequence"])
            if event["payload"]["content"]:
                break
    assert sequences == sorted(set(sequences))
    assert api("/runs/" + run_id)["status"] == "running"
    api(f"/runs/{run_id}/cancel", {})
    assert await_run(run_id)["status"] == "cancelled"


def run_smoke() -> None:
    first = str(api("/chats", {"title": "Проверка сохранности"})["id"])
    second = str(api("/chats", {"title": "Независимый чат"})["id"])
    run = start(first, "Проверка сохранения истории")
    assert await_run(run)["status"] == "completed"
    stream_disconnect(first)
    interrupted = start(first, "[slow] abrupt restart")
    partial = str(await_run(interrupted, terminal=False)["content"])
    compose("kill", "-s", "SIGKILL", "backend")
    compose("up", "-d", "--wait", "backend")
    restored = api("/runs/" + interrupted)
    assert restored["status"] == "failed"
    assert restored["incomplete"] is True
    assert str(restored["content"]).startswith(partial)
    compose("restart", "postgres")
    compose("up", "-d", "--wait", "postgres")
    assert api(f"/chats/{second}")["messages"] == []
    assert len(api(f"/chats/{first}")["messages"]) == 6
    try:
        compose("stop", "postgres")
        for path in ("/health/ready", "/chats"):
            try:
                api(path)
            except urllib.error.HTTPError as error:
                assert error.code == 503
            else:
                raise AssertionError("Unavailable PostgreSQL was reported as available")
    finally:
        compose("up", "-d", "--wait", "postgres")
    assert api("/health/ready")["status"] == "ready"
    assert len(api(f"/chats/{first}")["messages"]) == 6
    print("Runtime smoke passed: SSE disconnect, cancellation, abrupt restart, PostgreSQL restart/outage, isolated history.")


if __name__ == "__main__":
    run_smoke()

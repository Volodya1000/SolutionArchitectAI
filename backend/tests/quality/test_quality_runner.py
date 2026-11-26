from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tools import quality


def test_push_guard_rejects_a_different_committed_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "proof")
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/other")

    def revision(arguments: Sequence[str]) -> str:
        return "head-sha" if arguments[-1] == "HEAD" else "different-sha"

    monkeypatch.setattr(quality, "git_output", revision)
    with pytest.raises(RuntimeError, match="Checkout the branch"):
        quality.validate_push_checkout()


def test_push_guard_rejects_dirty_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "proof")
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/current")

    def revision(arguments: Sequence[str]) -> str:
        return " M tracked.py" if arguments[0] == "status" else "same-sha"

    monkeypatch.setattr(quality, "git_output", revision)
    with pytest.raises(RuntimeError, match="Commit or stash"):
        quality.validate_push_checkout()


def test_fresh_local_browser_installs_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(_title: str, arguments: Sequence[str], _env: Mapping[str, str], *, cwd: Path) -> None:
        assert cwd == quality.ROOT / "frontend"
        commands.append(list(arguments))

    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setattr(quality, "pnpm", lambda: "pnpm")
    monkeypatch.setattr(quality, "run", run)
    result: dict[str, str] = quality.browser_environment({})
    assert "PLAYWRIGHT_CHANNEL" not in result
    assert commands == [["pnpm", "exec", "playwright", "install", "--with-deps", "chromium"]]

"""The shared local-hook and CI quality entrypoint. Run from the repository root."""

import argparse
import os
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.quality_runtime import RuntimeEnvironment, isolated_runtime

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PYTHON: Final[str] = sys.executable
TARGETS: Final[tuple[str, ...]] = ("backend/src", "backend/tests", "tools")
CONFIG: Final[str] = "backend/pyproject.toml"


def git_output(arguments: Sequence[str]) -> str:
    executable: str | None = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is required for checkout validation")

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [executable, *arguments], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def validate_push_checkout() -> None:
    if not os.environ.get("PRE_COMMIT_REMOTE_NAME"):
        return
    branch: str | None = os.environ.get("PRE_COMMIT_LOCAL_BRANCH")
    if not branch or git_output(["rev-parse", branch]) != git_output(["rev-parse", "HEAD"]):
        raise RuntimeError("Checkout the branch being pushed before running its full checks")
    if git_output(["status", "--porcelain", "--untracked-files=normal"]):
        raise RuntimeError("Commit or stash changes before pushing the checked revision")


def run(title: str, arguments: Sequence[str], env: Mapping[str, str], *, cwd: Path = ROOT) -> None:
    print(f"Quality: {title}", flush=True)
    subprocess.run(  # nosec B603
        arguments,
        cwd=cwd,
        env=env,
        check=True,
        timeout=1800,
    )


def pnpm() -> str:
    executable: str | None = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if executable is None:
        raise RuntimeError("pnpm 12 is required; see README development setup")
    return executable


def python_tool(name: str, *arguments: str) -> list[str]:
    return [PYTHON, "-m", name, *arguments]


def clean_environment() -> dict[str, str]:
    env: dict[str, str] = {
        key: value for key, value in os.environ.items() if not key.startswith(("SAA_", "COMPOSE_"))
    }
    env["PYTHONUTF8"] = "1"
    env["COVERAGE_FILE"] = str(ROOT / ".build" / "backend.coverage")
    return env


def quality_binary(name: str) -> Path:
    return ROOT / ".build" / "quality-tools" / name / (name + (".exe" if os.name == "nt" else ""))


def setup(env: dict[str, str]) -> None:
    run("locked Python dependencies", ["uv", "sync", "--locked", "--project", "backend"], env)
    run(
        "locked frontend dependencies",
        [pnpm(), "--dir", "frontend", "install", "--frozen-lockfile"],
        env,
    )
    run("pinned repository tools", python_tool("tools.install_quality_tools"), env)
    browser_environment(env)
    run(
        "install commit and push hooks",
        [
            "uv",
            "run",
            "--locked",
            "--project",
            "backend",
            "pre-commit",
            "install",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "pre-push",
        ],
        env,
    )


def backend_static(env: dict[str, str]) -> None:
    run(
        "Python environment matches lockfile",
        ["uv", "sync", "--locked", "--check", "--project", "backend"],
        env,
    )
    run("Ruff", python_tool("ruff", "check", "--config", CONFIG, *TARGETS), env)
    run("Ruff format", python_tool("ruff", "format", "--check", "--config", CONFIG, *TARGETS), env)
    run(
        "Mypy strict: source, tests, tools",
        python_tool("mypy", "--config-file", CONFIG, *TARGETS),
        env,
    )
    run("Pylint source, tests and tools", python_tool("pylint", "--rcfile", CONFIG, *TARGETS), env)
    run("Bandit source", python_tool("bandit", "-c", CONFIG, "-r", "backend/src", "-q"), env)
    run(
        "Bandit tests and tools",
        python_tool("bandit", "-r", "backend/tests", "tools", "-s", "B101", "-q"),
        env,
    )
    run(
        "application import contracts",
        ["uv", "run", "--locked", "--project", "backend", "lint-imports", "backend/.importlinter"],
        env,
    )
    run(
        "Python cognitive complexity",
        python_tool("flake8", "--config", "backend/.flake8", *TARGETS),
        env,
    )


def frontend_fast(env: dict[str, str]) -> None:
    if not (ROOT / "frontend/node_modules").is_dir():
        raise RuntimeError("Frontend dependencies are missing; run tools.quality setup")
    script: str
    for script in ("lint", "format:check", "typecheck", "test"):
        run(f"frontend {script}", [pnpm(), script], env, cwd=ROOT / "frontend")


def repository_static(env: dict[str, str]) -> None:
    name: str
    for name in ("actionlint", "typos"):
        if not quality_binary(name).is_file():
            raise RuntimeError("Pinned repository tools are missing; run tools.quality setup")
        run(name, [str(quality_binary(name))], env)
    run("YAML", python_tool("yamllint", "."), env)
    run(
        "Markdown",
        ["node", "frontend/node_modules/markdownlint-cli2/markdownlint-cli2-bin.mjs"],
        env,
    )
    run("local documentation links", python_tool("tools.check_links"), env)
    run("hook configuration", python_tool("pre_commit", "validate-config"), env)


def fast(env: dict[str, str]) -> None:
    backend_static(env)
    frontend_fast(env)
    repository_static(env)
    run(
        "fast Python unit tests",
        python_tool(
            "pytest",
            "-c",
            CONFIG,
            "backend/tests/unit",
            "backend/tests/quality/test_quality_runtime.py",
            "backend/tests/quality/test_quality_runner.py",
            "backend/tests/quality/test_runtime_smoke.py",
            "backend/tests/quality/test_gates.py::test_resource_construction_stays_in_composition_and_scoped_factories",
            "--cov",
            "--cov-config=backend/pyproject.toml",
            "--cov-report=",
            "--cov-fail-under=0",
            "--disable-socket",
            "--allow-hosts=127.0.0.1,localhost",
            "--allow-unix-socket",
        ),
        env,
    )


def audit(env: dict[str, str]) -> None:
    run(
        "frontend dependency audit",
        [pnpm(), "audit", "--audit-level", "low"],
        env,
        cwd=ROOT / "frontend",
    )
    requirements: Path = ROOT / ".build" / "quality-requirements.txt"
    requirements.parent.mkdir(exist_ok=True)
    run(
        "export hashed Python dependencies",
        [
            "uv",
            "export",
            "--project",
            "backend",
            "--frozen",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        ],
        env,
    )
    run(
        "Python dependency audit",
        [
            "uvx",
            "pip-audit==2.10.1",
            "--require-hashes",
            "--no-deps",
            "--disable-pip",
            "-r",
            str(requirements),
        ],
        env,
    )


def browser_environment(env: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = dict(env)
    if os.name == "nt" and not result.get("CI"):
        base: str = os.environ.get("PROGRAMFILES(X86)", "")
        if base and (Path(base) / "Microsoft/Edge/Application/msedge.exe").is_file():
            result.setdefault("PLAYWRIGHT_CHANNEL", "msedge")
    if not result.get("PLAYWRIGHT_CHANNEL"):
        run(
            "Chromium and system dependencies",
            [pnpm(), "exec", "playwright", "install", "--with-deps", "chromium"],
            result,
            cwd=ROOT / "frontend",
        )
    return result


def acceptance(env: dict[str, str]) -> None:
    prepared: dict[str, str] = browser_environment(env)
    runtime: RuntimeEnvironment
    with isolated_runtime(ROOT) as runtime:
        backend: dict[str, str] = dict(runtime.backend)
        backend["COVERAGE_FILE"] = env["COVERAGE_FILE"]
        run(
            "migrate dedicated test database",
            python_tool(
                "coverage",
                "run",
                "--rcfile",
                CONFIG,
                "--append",
                "-m",
                "solution_architect_ai.di.migrate",
            ),
            backend,
        )
        run(
            "PostgreSQL and adapter integration tests",
            python_tool(
                "pytest",
                "-c",
                CONFIG,
                "backend/tests/integration",
                "--cov",
                "--cov-config=backend/pyproject.toml",
                "--cov-append",
                "--cov-report=term-missing:skip-covered",
                "--cov-report=xml:.build/backend-coverage.xml",
                "--cov-report=json:.build/backend-coverage.json",
                "--disable-socket",
                "--allow-hosts=127.0.0.1,localhost",
                "--allow-unix-socket",
            ),
            backend,
        )
        browser: dict[str, str] = dict(runtime.browser)
        if "PLAYWRIGHT_CHANNEL" in prepared:
            browser["PLAYWRIGHT_CHANNEL"] = prepared["PLAYWRIGHT_CHANNEL"]
        run("browser acceptance", [pnpm(), "test:e2e"], browser, cwd=ROOT / "frontend")
        run("isolated restart and failure smoke", python_tool("tools.runtime_smoke"), browser)


def full(env: dict[str, str]) -> None:
    validate_push_checkout()
    fast(env)
    run(
        "Python quality gate probes",
        python_tool("pytest", "-c", CONFIG, "backend/tests/quality"),
        env,
    )
    run(
        "frontend architecture and type probes",
        ["node", "scripts/check-contracts.mjs"],
        env,
        cwd=ROOT / "frontend",
    )
    run("frontend production build", [pnpm(), "build"], env, cwd=ROOT / "frontend")
    audit(env)
    acceptance(env)


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("setup", "fast", "full"))
    args: argparse.Namespace = parser.parse_args()
    mode: str = args.mode
    env: dict[str, str] = clean_environment()
    try:
        if mode == "setup":
            setup(env)
        elif mode == "fast":
            fast(env)
        else:
            full(env)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Quality failed: {error}\n")
    print(f"Quality {mode}: passed.", flush=True)


if __name__ == "__main__":
    main()

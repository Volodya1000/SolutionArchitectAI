import ast
import os
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("module", "arguments", "source", "diagnostic"),
    [
        ("ruff", ["check", "--select", "F821"], "missing_name()\n", "F821"),
        (
            "pylint",
            ["--disable=all", "--enable=no-member"],
            "class Item:\n    value = 1\nItem().absent()\n",
            "E1101",
        ),
        (
            "bandit",
            ["-q"],
            "import subprocess\nsubprocess.run('echo bad', shell=True)\n",
            "B602",
        ),
        (
            "flake8",
            ["--select=WPS231", "--max-cognitive-score=12"],
            "def complex_case(a):\n    for b in a:\n        for c in b:\n            for d in c:\n                if d:\n                    if d > 1:\n                        return d\n",
            "WPS231",
        ),
    ],
)
def test_tools_reject_the_intended_defect(
    tmp_path: Path, module: str, arguments: list[str], source: str, diagnostic: str
) -> None:
    probe: Path = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [sys.executable, "-m", module, *arguments, str(probe)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr


def test_import_contract_rejects_a_domain_to_persistence_dependency(tmp_path: Path) -> None:
    probe_directory: Path
    for probe_directory in (tmp_path / "backend/tests", tmp_path / "backend/test_helpers"):
        probe_directory.mkdir(parents=True)
        (probe_directory / "__init__.py").touch()
    package: Path = tmp_path / "solution_architect_ai"
    package.mkdir()
    (package / "__init__.py").touch()
    name: str
    for name in (
        "domain",
        "application",
        "persistence",
        "presentation",
        "infrastructure",
        "di",
        "config",
    ):
        directory: Path = package / name
        directory.mkdir()
        (directory / "__init__.py").touch()
    (package / "domain/invalid.py").write_text(
        "import solution_architect_ai.persistence\n", encoding="utf-8"
    )
    config: Path = Path(__file__).parents[2] / ".importlinter"

    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            str(config),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(config.parents[1]), str(tmp_path)])},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "BROKEN" in result.stdout


def constructor_calls(tree: ast.AST, names: set[str]) -> Iterator[ast.Call]:
    node: ast.AST
    name: str
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Name(id=name) | ast.Attribute(attr=name)) if name in names:
                yield node


def test_resource_construction_stays_in_composition_and_scoped_factories() -> None:
    source: Path = Path(__file__).parents[2] / "src/solution_architect_ai"
    owners: set[str] = {
        "di/providers.py",
        "di/migrate.py",
        "di/documents.py",
        "di/extraction.py",
        "di/clarifications.py",
        "di/discussions.py",
    }
    constructors: set[str] = {
        "AsyncSession",
        "create_async_engine",
        "async_sessionmaker",
        "AsyncClient",
    }
    violations: list[str] = []
    path: Path
    for path in source.rglob("*.py"):
        relative: str = path.relative_to(source).as_posix()
        if relative in owners:
            continue
        tree: ast.Module = ast.parse(path.read_text(encoding="utf-8"))
        violations.extend(
            f"{relative}:{node.lineno}" for node in constructor_calls(tree, constructors)
        )
    assert not violations

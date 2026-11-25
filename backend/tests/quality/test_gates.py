import ast
import os
import subprocess
import sys
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
        ("bandit", ["-q"], "import subprocess\nsubprocess.run('echo bad', shell=True)\n", "B602"),
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
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", module, *arguments, str(probe)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr


def test_import_contract_rejects_a_domain_to_persistence_dependency(tmp_path: Path) -> None:
    package = tmp_path / "solution_architect_ai"
    package.mkdir()
    (package / "__init__.py").touch()
    for name in (
        "domain",
        "application",
        "persistence",
        "presentation",
        "infrastructure",
        "di",
        "config",
    ):
        directory = package / name
        directory.mkdir()
        (directory / "__init__.py").touch()
    (package / "domain/invalid.py").write_text(
        "import solution_architect_ai.persistence\n", encoding="utf-8"
    )
    config = Path(__file__).parents[2] / ".importlinter"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            str(config),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "BROKEN" in result.stdout


def test_resource_construction_stays_in_composition_and_scoped_factories() -> None:
    source = Path(__file__).parents[2] / "src/solution_architect_ai"
    owners = {"di/providers.py", "di/migrate.py", "persistence/factory.py"}
    constructors = {"AsyncSession", "create_async_engine", "async_sessionmaker", "AsyncClient"}
    violations: list[str] = []
    for path in source.rglob("*.py"):
        relative = path.relative_to(source).as_posix()
        if relative in owners:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if name in constructors:
                    violations.append(f"{relative}:{node.lineno}")
    assert violations == []

"""Import-linter contract for pytest modules, including their filesystem aliases."""

import ast
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from grimp import ImportGraph
from importlinter.application import output
from importlinter.domain.contract import Contract, ContractCheck

GENERATED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        ".build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".import_linter_cache",
        "node_modules",
        "__pycache__",
    }
)


@dataclass(frozen=True)
class TestImportViolation:
    importer: str
    line: int
    imported: str


def python_files(root: Path) -> Iterator[Path]:
    directory: Path
    directory_names: list[str]
    file_names: list[str]
    for directory, directory_names, file_names in root.walk():
        directory_names[:] = sorted(set(directory_names) - GENERATED_DIRECTORIES)
        yield from (directory / name for name in sorted(file_names) if name.endswith(".py"))


def module_name(path: Path, root: Path) -> str:
    relative: Path = path.relative_to(root).with_suffix("")
    if relative.name == "__init__":
        relative = relative.parent
    return ".".join(relative.parts)


def test_module_aliases(paths: Sequence[Path], root: Path) -> dict[str, str]:
    aliases: dict[str, str] = {"backend.tests": "backend.tests", "tests": "backend.tests"}
    path: Path
    for path in paths:
        if path.is_relative_to(root / "backend/tests"):
            canonical: str = module_name(path, root)
            components: list[str] = canonical.split(".")
            index: int
            for index in range(len(components)):
                aliases.setdefault(".".join(components[index:]), canonical)
    return aliases


def import_from_module(node: ast.ImportFrom, path: Path, root: Path) -> str:
    if not node.level:
        return node.module or ""
    package: list[str] = list(path.parent.relative_to(root).parts)
    if node.level > len(package):
        return ""
    prefix: list[str] = package[: len(package) - node.level + 1]
    return ".".join([*prefix, *([node.module] if node.module else [])])


def imported_modules(node: ast.Import | ast.ImportFrom, path: Path, root: Path) -> Iterator[str]:
    if isinstance(node, ast.Import):
        yield from (alias.name for alias in node.names)
        return
    module: str = import_from_module(node, path, root)
    if module:
        yield from (f"{module}.{alias.name}" for alias in node.names if alias.name != "*")
        yield module


def test_import_target(
    node: ast.Import | ast.ImportFrom, path: Path, root: Path, aliases: dict[str, str]
) -> str | None:
    return next(
        (aliases[name] for name in imported_modules(node, path, root) if name in aliases), None
    )


def file_violations(
    path: Path, root: Path, aliases: dict[str, str]
) -> Iterator[TestImportViolation]:
    tree: ast.Module = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    node: ast.AST
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        target: str | None = test_import_target(node, path, root, aliases)
        if target is not None:
            yield TestImportViolation(module_name(path, root), node.lineno, target)


def forbidden_test_imports(root: Path) -> list[TestImportViolation]:
    paths: list[Path] = list(python_files(root))
    aliases: dict[str, str] = test_module_aliases(paths, root)
    return [violation for path in paths for violation in file_violations(path, root, aliases)]


def find_repository_root(directory: Path) -> Path:
    start: Path = directory.resolve()
    candidate: Path
    for candidate in (start, *start.parents):
        if (candidate / "backend/tests").is_dir():
            return candidate
    raise ValueError("Cannot locate a repository containing backend/tests")


class TestIndependenceContract(Contract):
    type_name: Final[str] = "test_independence"
    violations: list[TestImportViolation]

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        del graph, verbose
        self.violations = forbidden_test_imports(find_repository_root(Path.cwd()))
        return ContractCheck(kept=not self.violations)

    def render_broken_contract(self, check: ContractCheck) -> None:
        del check
        violation: TestImportViolation
        for violation in self.violations:
            output.print(f"{violation.importer}:{violation.line} imports {violation.imported}")
        output.print(
            "Put shared builders and fakes in backend.test_helpers and fixtures in the nearest "
            "conftest.py. Never import a test module or conftest.py."
        )

"""Reject SQLAlchemy session specs in test doubles; persistence needs PostgreSQL."""

import ast
from pathlib import Path
from typing import Final

MOCKS: Final[frozenset[str]] = frozenset(
    f"unittest.mock.{name}" for name in ("Mock", "MagicMock", "AsyncMock")
)
SESSIONS: Final[frozenset[str]] = frozenset(
    (
        "sqlalchemy.orm.Session",
        "sqlalchemy.orm.session.Session",
        "sqlalchemy.ext.asyncio.AsyncSession",
        "sqlalchemy.ext.asyncio.session.AsyncSession",
    )
)


def import_bindings(node: ast.Import | ast.ImportFrom) -> dict[str, str]:
    if isinstance(node, ast.Import):
        return {
            alias.asname or alias.name.split(".")[0]: (
                alias.name if alias.asname else alias.name.split(".")[0]
            )
            for alias in node.names
        }
    if node.module and not node.level:
        return {alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names}
    return {}


def imported_names(tree: ast.Module) -> dict[str, str]:
    names: dict[str, str] = {}
    node: ast.AST
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(import_bindings(node))
    return names


def qualified_name(node: ast.expr, names: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{qualified_name(node.value, names)}.{node.attr}"
    if isinstance(node, ast.Call):
        return qualified_name(node.func, names)
    return ""


def session_mock_lines(source: str) -> list[int]:
    tree: ast.Module = ast.parse(source)
    names: dict[str, str] = imported_names(tree)
    lines: list[int] = []
    node: ast.AST
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or qualified_name(node.func, names) not in MOCKS:
            continue
        specs: list[ast.expr] = list(node.args[:1]) + [
            keyword.value for keyword in node.keywords if keyword.arg in {"spec", "spec_set"}
        ]
        if any(qualified_name(spec, names) in SESSIONS for spec in specs):
            lines.append(node.lineno)
    return sorted(lines)


def main() -> None:
    root: Path = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    directory: str
    for directory in ("backend/tests", "backend/test_helpers", "tools"):
        path: Path
        for path in sorted((root / directory).rglob("*.py")):
            failures.extend(
                f"{path.relative_to(root).as_posix()}:{line}: SQLAlchemy session mock spec"
                for line in session_mock_lines(path.read_text(encoding="utf-8"))
            )
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()

import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest


def write_module(root: Path, name: str, source: str = "") -> None:
    components: list[str] = name.split(".")
    package: Path = root
    component: str
    for component in components[:-1]:
        package /= component
        package.mkdir(exist_ok=True)
        if package != root / "backend":
            (package / "__init__.py").touch()
    (package / f"{components[-1]}.py").write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n",
        "import pytest as testing\n",
        "from pytest import raises as expect_failure\n",
        "import backend.test_helpers.shared as support\n",
        "from backend.test_helpers import shared as support\n",
        "from backend import test_helpers as support\n",
    ],
)
def test_product_cannot_depend_on_test_infrastructure(import_checkout: Path, source: str) -> None:
    write_module(import_checkout, "solution_architect_ai.domain.probe", source)
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "Product code does not depend on pytest or test helpers BROKEN" in result.stdout


def test_product_can_use_its_domain_without_test_infrastructure(import_checkout: Path) -> None:
    write_module(
        import_checkout,
        "solution_architect_ai.application.probe",
        "from solution_architect_ai import domain\n",
    )
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Product code does not depend on pytest or test helpers KEPT" in result.stdout


@pytest.fixture(name="import_checkout")
def import_checkout_fixture(tmp_path: Path) -> Path:
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
        write_module(tmp_path, f"solution_architect_ai.{name}.__init__")
    write_module(tmp_path, "backend.tests.unit.test_target", "VALUE: int = 1\n")
    write_module(tmp_path, "backend.tests.integration.test_target", "VALUE: int = 1\n")
    write_module(tmp_path, "backend.tests.new_suite.nested.test_target", "VALUE: int = 1\n")
    write_module(tmp_path, "backend.test_helpers.shared", "VALUE: int = 1\n")
    return tmp_path


def lint_imports(
    checkout: Path, *, working_directory: Path | None = None
) -> subprocess.CompletedProcess[str]:
    config: Path = Path(__file__).parents[2] / ".importlinter"
    return subprocess.run(  # nosec B603
        [
            sys.executable,
            "-P",
            "-c",
            # The synthetic tools package must not shadow the contract implementation.
            "import tools.test_import_contract; "
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            str(config),
            "--no-cache",
        ],
        cwd=working_directory or checkout,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(config.parents[1]), str(checkout)])},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("backend.tests.unit.test_source", "from backend.tests.unit.test_target import VALUE\n"),
        ("backend.tests.unit.test_source", "from .test_target import VALUE\n"),
        (
            "backend.tests.unit.test_source",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from backend.tests.unit.test_target import VALUE\n",
        ),
        (
            "backend.tests.integration.test_source",
            "from backend.tests.unit.test_target import VALUE\n",
        ),
        (
            "backend.tests.unit.test_source",
            "from backend.tests.integration.test_target import VALUE\n",
        ),
        (
            "backend.tests.unit.test_source",
            "from backend.tests.new_suite.nested.test_target import VALUE\n",
        ),
        (
            "backend.tests.new_suite.nested.test_source",
            "from backend.tests.unit.test_target import VALUE\n",
        ),
        ("backend.test_helpers.shared", "from backend.tests.unit.test_target import VALUE\n"),
        ("backend.test_helpers.__init__", "from backend.tests.unit.test_target import VALUE\n"),
        ("backend.tests.unit.test_source", "from tests.unit.test_target import VALUE\n"),
        ("backend.tests.unit.test_source", "from test_target import VALUE\n"),
        ("backend.tests.unit.test_source", "import test_target\n"),
        ("backend.tests.unit.test_source", "from tests.unit import test_target\n"),
        ("backend.tests.unit.test_source", "from . import test_target\n"),
        ("backend.tests.unit.test_source", "import tests.unit.test_target as shared\n"),
    ],
)
def test_import_contract_rejects_test_module_dependencies(
    import_checkout: Path, module: str, source: str
) -> None:
    write_module(import_checkout, module, source)
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "Test modules are independent" in result.stdout
    assert "BROKEN" in result.stdout
    assert "test_target" in result.stdout


def test_import_contract_rejects_test_dependency_hidden_in_helper(import_checkout: Path) -> None:
    write_module(
        import_checkout,
        "backend.test_helpers.shared",
        "from backend.tests.unit.test_target import VALUE\n",
    )
    write_module(
        import_checkout,
        "backend.tests.unit.test_source",
        "from backend.test_helpers.shared import VALUE\n",
    )
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "backend.test_helpers.shared" in result.stdout
    assert "backend.tests.unit.test_target" in result.stdout


def test_import_contract_rejects_explicit_conftest_import(import_checkout: Path) -> None:
    write_module(import_checkout, "backend.tests.unit.conftest", "VALUE: int = 1\n")
    write_module(
        import_checkout,
        "backend.tests.unit.test_source",
        "from backend.tests.unit.conftest import VALUE\n",
    )
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "backend.tests.unit.conftest" in result.stdout


@pytest.mark.parametrize("source", ["from tests.unit.conftest import VALUE\n", "import conftest\n"])
def test_import_contract_rejects_aliased_conftest_import(
    import_checkout: Path, source: str
) -> None:
    write_module(import_checkout, "backend.tests.unit.conftest", "VALUE: int = 1\n")
    write_module(import_checkout, "backend.tests.unit.test_source", source)
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "conftest" in result.stdout


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (
            "backend.tests.new_suite.nested.test_source",
            "from backend.tests.unit.test_target import VALUE\n",
        ),
        (
            "backend.tests.unit.test_source",
            "from backend.tests.new_suite.nested.test_target import VALUE\n",
        ),
    ],
)
def test_import_contract_rejects_import_in_unpackaged_test_folder(
    import_checkout: Path, module: str, source: str
) -> None:
    write_module(import_checkout, module, source)
    (import_checkout / "backend/tests/new_suite/__init__.py").unlink()
    (import_checkout / "backend/tests/new_suite/nested/__init__.py").unlink()
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "test_source" in result.stdout


def test_import_contract_rejects_test_dependency_hidden_in_tools(import_checkout: Path) -> None:
    write_module(
        import_checkout,
        "tools.bridge",
        "from backend.tests.unit.test_target import VALUE\n",
    )
    write_module(
        import_checkout,
        "backend.tests.unit.test_source",
        "from tools.bridge import VALUE\n",
    )
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "tools" in result.stdout
    assert "test_target" in result.stdout


def test_import_contract_rejects_test_import_when_run_from_backend(import_checkout: Path) -> None:
    write_module(
        import_checkout,
        "backend.tests.unit.test_source",
        "from tests.unit.test_target import VALUE\n",
    )
    result: subprocess.CompletedProcess[str] = lint_imports(
        import_checkout, working_directory=import_checkout / "backend"
    )
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "test_target" in result.stdout


def test_import_contract_fails_without_a_checkout_root(
    import_checkout: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    working_directory: Path = tmp_path_factory.mktemp("outside_checkout")
    result: subprocess.CompletedProcess[str] = lint_imports(
        import_checkout, working_directory=working_directory
    )
    assert result.returncode != 0
    assert "Cannot locate a repository containing backend/tests" in result.stdout


@pytest.mark.parametrize("packaged", [True, False])
def test_import_contract_allows_helpers_and_pytest_fixture_discovery(
    import_checkout: Path, *, packaged: bool
) -> None:
    write_module(
        import_checkout,
        "backend.tests.unit.conftest",
        "import pytest\nfrom backend.test_helpers.shared import VALUE\n"
        "@pytest.fixture\ndef shared_value() -> int:\n    return VALUE\n",
    )
    write_module(
        import_checkout,
        "backend.tests.unit.test_source",
        "from backend.test_helpers.shared import VALUE\n"
        "def test_shared(shared_value: int) -> None:\n    assert shared_value == VALUE\n",
    )
    if not packaged:
        (import_checkout / "backend/tests/unit/__init__.py").unlink()
    result: subprocess.CompletedProcess[str] = lint_imports(import_checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    collection: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "backend/tests", "-q"],
        cwd=import_checkout,
        env={**os.environ, "PYTHONPATH": str(import_checkout)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert collection.returncode == 0, collection.stdout + collection.stderr
    assert "1 passed" in collection.stdout

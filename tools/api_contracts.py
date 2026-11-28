import argparse
import os
import shutil
import subprocess  # nosec B404
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal

from tools.export_openapi import export_openapi

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
FRONTEND: Final[Path] = ROOT / "frontend"
GENERATED: Final[Path] = FRONTEND / "src/shared/api/generated"


def generate_artifacts(directory: Path) -> dict[Path, bytes]:
    schema: Path = directory / "openapi.json"
    output: Path = directory / "generated"
    export_openapi(schema)
    pnpm: str | None = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if pnpm is None:
        raise RuntimeError("pnpm 12 is required to generate HTTP contracts")
    environment: dict[str, str] = {
        **os.environ,
        "OPENAPI_INPUT": str(schema),
        "OPENAPI_OUTPUT": str(output),
    }
    subprocess.run(  # nosec B603
        [pnpm, "exec", "openapi-ts"],
        cwd=FRONTEND,
        env=environment,
        check=True,
    )
    subprocess.run(  # nosec B603
        [
            pnpm,
            "exec",
            "prettier",
            "--write",
            "--config",
            ".prettierrc.json",
            str(schema),
            str(output),
        ],
        cwd=FRONTEND,
        check=True,
    )
    return {
        FRONTEND / "openapi.json": schema.read_bytes(),
        **{GENERATED / path.name: path.read_bytes() for path in output.glob("*.ts")},
    }


def changed_artifacts(expected: dict[Path, bytes]) -> list[Path]:
    changed: list[Path] = [
        path
        for path, content in expected.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    return sorted(set(changed) | (set(GENERATED.glob("*.ts")) - expected.keys()))


def run(mode: Literal["generate", "check"]) -> int:
    build: Path = ROOT / ".build"
    build.mkdir(exist_ok=True)
    temporary: str
    with TemporaryDirectory(prefix="api-contracts-", dir=build) as temporary:
        artifacts: dict[Path, bytes] = generate_artifacts(Path(temporary))
        changed: list[Path] = changed_artifacts(artifacts)
        path: Path
        content: bytes
        if mode == "check":
            if changed:
                print("HTTP contracts differ; run pnpm --dir frontend api:generate")
                for path in changed:
                    print(path.relative_to(ROOT))
                return 1
            print("HTTP contracts match the offline backend schema")
            return 0
        for path in set(GENERATED.glob("*.ts")) - artifacts.keys():
            path.unlink()
        for path, content in artifacts.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return 0


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("generate", "check"))
    mode: Literal["generate", "check"] = parser.parse_args().mode
    raise SystemExit(run(mode))


if __name__ == "__main__":
    main()

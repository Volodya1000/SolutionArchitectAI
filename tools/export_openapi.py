import argparse
import json
from pathlib import Path

from solution_architect_ai.presentation.api import create_http_app


def export_openapi(output: Path) -> None:
    schema: dict[str, object] = create_http_app().openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    output: Path = parser.parse_args().output
    export_openapi(output)


if __name__ == "__main__":
    main()

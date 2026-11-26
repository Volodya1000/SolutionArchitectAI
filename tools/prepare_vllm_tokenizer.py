"""Fetch only pinned tokenizer/config files; never download model weights."""

import hashlib
import urllib.request
from pathlib import Path
from typing import BinaryIO, Final, TypedDict

from pydantic import TypeAdapter


class Manifest(TypedDict):
    repository: str
    revision: str
    files: dict[str, str]


MANIFEST: Final[TypeAdapter[Manifest]] = TypeAdapter(Manifest)


def prepare() -> Path:
    root: Path = Path(__file__).resolve().parents[1]
    manifest: Manifest = MANIFEST.validate_json((root / "tools/vllm-tokenizer.json").read_bytes())
    directory: Path = root / ".build/vllm-tokenizer"
    directory.mkdir(parents=True, exist_ok=True)
    name: str
    digest: str
    for name, digest in manifest["files"].items():
        target: Path = directory / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        url: str = (
            f"https://huggingface.co/{manifest['repository']}/resolve/{manifest['revision']}/{name}"
        )
        response: BinaryIO

        with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310
            data: bytes = response.read(20 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Tokenizer checksum mismatch")
        target.write_bytes(data)
    return directory


if __name__ == "__main__":
    print(prepare())

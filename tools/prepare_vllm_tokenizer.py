"""Fetch only pinned tokenizer/config files; never download model weights."""
import hashlib
import json
import urllib.request
from pathlib import Path


def prepare() -> Path:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "tools/vllm-tokenizer.json").read_text(encoding="utf-8"))
    directory = root / ".build/vllm-tokenizer"
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest["files"].items():
        target = directory / name
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            continue
        url = f'https://huggingface.co/{manifest["repository"]}/resolve/{manifest["revision"]}/{name}'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(20 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Tokenizer checksum mismatch")
        target.write_bytes(data)
    return directory


if __name__ == "__main__":
    print(prepare())

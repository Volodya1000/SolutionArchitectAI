"""Check local Markdown destinations without making network requests."""
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def check() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "ls-files", "*.md"], cwd=root, check=True, capture_output=True, text=True)
    failures: list[str] = []
    for name in result.stdout.splitlines():
        document = root / name
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.DOTALL)
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            destination = match.group(1).strip().split(' "', 1)[0].strip("<>")
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (document.parent / unquote(parsed.path)).resolve()
            if not target.is_file():
                failures.append(f"{name}: {destination}")
    if failures:
        raise ValueError("Broken local links:\n" + "\n".join(failures))
    print("Local Markdown destinations passed.")


if __name__ == "__main__":
    check()

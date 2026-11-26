"""Check local Markdown destinations without making network requests."""

import re
import shutil

# Git lists only the tracked Markdown files.
import subprocess  # nosec B404
from pathlib import Path
from urllib.parse import SplitResult, unquote, urlsplit


def broken_links(document: Path, name: str) -> list[str]:
    markdown: str = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.DOTALL)
    failures: list[str] = []
    match: re.Match[str]
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", markdown):
        destination: str = match.group(1).strip().split(' "', 1)[0].strip("<>")
        parsed: SplitResult = urlsplit(destination)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target: Path = (document.parent / unquote(parsed.path)).resolve()
        if not target.is_file():
            failures.append(f"{name}: {destination}")
    return failures


def check() -> None:
    root: Path = Path(__file__).resolve().parents[1]
    git: str | None = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required to list tracked Markdown files")
    # Use the installed Git and fixed read-only arguments without a shell.
    result: subprocess.CompletedProcess[str] = subprocess.run(  # nosec B603
        [git, "ls-files", "*.md"], cwd=root, check=True, capture_output=True, text=True
    )
    failures: list[str] = [
        failure
        for name in result.stdout.splitlines()
        for failure in broken_links(root / name, name)
    ]
    if failures:
        raise ValueError("Broken local links:\n" + "\n".join(failures))
    print("Local Markdown destinations passed.")


if __name__ == "__main__":
    check()

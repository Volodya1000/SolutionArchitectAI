import re
from collections.abc import Mapping
from typing import Final

_REFERENCE: Final[re.Pattern[str]] = re.compile(r"\[([^\]\n]*)\]\(([^)]*)\)")
_URL: Final[re.Pattern[str]] = re.compile(
    r"https?://[^\s<>()`]+|/(?:documents|requirements)\?[^\s<>()`]+"
)
_URL_PREFIXES: Final[tuple[str, ...]] = ("http://", "https://", "/documents?", "/requirements?")
_MAX_PENDING: Final[int] = 8192


class DiscussionCitationStream:
    def __init__(self, references: Mapping[str, str] | None) -> None:
        self.references: Mapping[str, str] | None = references
        self.pending: str = ""

    def replace(self, match: re.Match[str]) -> str:
        target: str | None = (
            self.references.get(match[2][4:])
            if self.references is not None and match[2].startswith("ref:")
            else None
        )
        return f"[{match[1]}]({target})" if target else match[1]

    def feed(self, text: str, *, final: bool = False) -> str:
        if self.references is None:
            return text
        self.pending += text
        boundary: int = self.ready_boundary(final=final)
        ready: str = self.pending[:boundary]
        self.pending = self.pending[boundary:]
        if len(self.pending) > _MAX_PENDING:
            # An unfinished model token must not hold the response indefinitely or
            # later join emitted text into an unchecked link.
            self.pending = ""
            ready += " Citation omitted. "
        return _URL.sub(self.neutralize_url, _REFERENCE.sub(self.replace, ready))

    def ready_boundary(self, *, final: bool) -> int:
        if final:
            return len(self.pending)
        boundary: int = self.pending.rfind("[")
        if boundary < 0 or ")" in self.pending[boundary:]:
            boundary = len(self.pending)
        match: re.Match[str]
        for match in _URL.finditer(self.pending):
            if match.end() == len(self.pending):
                boundary = min(boundary, match.start())
        prefix: str
        length: int
        for prefix in _URL_PREFIXES:
            for length in range(1, len(prefix) + 1):
                if self.pending.endswith(prefix[:length]):
                    boundary = min(boundary, len(self.pending) - length)
        return boundary

    def neutralize_url(self, match: re.Match[str]) -> str:
        target: str = match[0]
        return (
            target
            if self.references is not None and target in self.references.values()
            else f"`{target}`"
        )

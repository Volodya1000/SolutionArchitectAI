# PR 20 derived parser metadata integrity

The saved-parse structure trust path was reproduced with persisted JSON carrying
forged, well-typed `DocumentStructure` and its unchanged legacy digest. Before the
fix, seven new cases failed and two passed. The forged metadata could mark TXT
content as Markdown structure. Fresh PDF/DOCX reads also parsed twice.

`DocumentService` now derives Markdown structure only from verified original
bytes and authoritative version MIME. A fresh parse produced during the current
call is reused; structure returned by persistence is never trusted. Non-Markdown
reads force `structure=None`, so cached TXT/PDF/DOCX reads do not reparse.
Stored fragments, IDs, locators, SHA-256, warnings, and digest remain unchanged.
Metadata is still excluded from persisted parse serialization and legacy digest.

The new direct-service regression uses real `LocalFileStorage` byte/hash checking,
real Markdown/TXT/DOCX/PDF parsing, and a fake persistence read containing tampered
serialized JSON. It covers fresh/cached reads for all four formats, exact parse
call counts, and legacy Markdown reads without rewriting saved source fragments.
No paid calls, root-worktree writes, or production database access were required.

Verification:

- New integrity tests plus existing parser acceptance tests: **21 passed**, 3.29 s.
- New integrity cases alone: **9 cases**, including the old digest equality proof.
- Ruff and formatting: **passed**.
- Strict Mypy on the service and regression: **passed**, two files.
- Pylint: **10.00/10**; cognitive complexity: **passed**.
- Bandit on the regression: **passed**.

The separately exported annotation-only patch adds the 17 previously reported
loop/context-manager binding declarations and required type imports. Strict
Mypy shadow checks against the current root source pass for all eight files.

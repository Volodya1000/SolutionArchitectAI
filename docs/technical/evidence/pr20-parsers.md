# PR 20 parser acceptance evidence

Date: 2026-11-28. Base: `269626a7d3b88293624a419e3ff56983429b9d66`.
Isolated branch: `codex/pr20-parser-acceptance-fix`.

## Reproduction and correction

The new backend regressions first produced **5 failed, 1 passed**: literal TXT and
fenced-code candidates were discarded by the pipe/dash heuristic; a real table
separator leaked into semantic extraction; table headers were lost across context
windows; an omitted DOCX first cell shifted column headings and source paths.
A later distant-row discussion regression produced **1 failed, 1 passed** before
adding the actual table header to the related source context.
The new source-viewer tests first produced **2 failed** before the viewer change.

Markdown structure now comes from markdown-it-py table tokens and physical line
maps. TXT and fenced code have no inferred table structure. In
`docs/examples/pr3/reporting-system-incomplete.md`, physical line 48 remains the
header, line 49 remains the separator, and Kafka remains line 50. Original bytes,
SHA-256, physical line fragments, and UUIDv5 identities are unchanged. Separators
are omitted from extraction, clarification, and discussion neighbor context. A
selected technical separator is rejected as a semantic discussion source. Real
table headers accompany data rows across extraction/clarification windows and
are included as exact source references for distant discussion rows.

The source viewer omits the separator discussion card. An old link to the
separator fragment still resolves to its literal source text without a discussion
action. Saved parse serialization and its digest exclude derived structure.
Legacy parses receive runtime syntax metadata from original bytes while retaining
all saved fragments, IDs, locators, and hashes. Tests cover both Markdown and a
legacy DOCX saved before the column correction.

DOCX uses python-docx row grid offsets and its expanded merged-cell grid. In the
omitted-first-cell fixture, `30 дней` and `Отказать` belong to columns 2 and 3,
with headings `Срок хранения` and `Поведение` and corresponding source paths.
Merged cells remain emitted once per row.

## Commands and results

- `uv run --locked --project backend pytest backend/tests/unit/test_pr20_parser_acceptance.py -q`:
  **12 passed** (1.54 s), after the final test-helper cleanup.
- Focused parser/extraction/clarification command using
  `test_pr20_parser_acceptance.py`, `test_extraction_structure.py`,
  `test_document_parser.py`, `test_document_formats.py`, and
  `test_clarification_agent.py`: **42 passed** (2.59 s).
- `uv run --locked --project backend pytest backend/tests/unit -q`:
  **316 passed** (14.74 s). The previous raw-fragment coverage assertion was
  updated to count semantic fragments after excluding four recognized separators.
- `uv run --locked --project backend pytest backend/tests -q --maxfail=1`:
  stopped with **1 setup error**,
  `test_append_statement.py::test_append_persists_each_delta_in_one_statement`.
  The database safety assertion rejected the default database name
  `solution_architect` because it does not end in `_test`. Integration was not
  claimed to pass and no production database was contacted.
- Ruff source and changed tests: **passed**; Ruff format: **passed**.
- Mypy source and changed tests: **passed**, 162 source files checked.
- `uv run --locked --project backend lint-imports backend/.importlinter`:
  **4 contracts kept, 0 broken**.
- Focused Pylint covers Markdown structure, DOCX parser, discussion source context,
  and the parser regression file: **passed, 10.00/10**.
- `pnpm.cmd install --frozen-lockfile`: **passed**, pnpm 12.21.0; isolated
  worktree node_modules; existing D: package store reused without reconfiguration.
- `pnpm.cmd typecheck`, `pnpm.cmd lint`: **passed**.
- `pnpm.cmd test`: **106 passed**, 17 files; coverage statements 92.51%,
  branches 86.6%, functions 92.2%, lines 94.13%.
- `pnpm.cmd build`: **passed**, existing Vite warning for a chunk larger than
  500 kB after minification.
- `git diff --check`: **passed**.

No commit, push, or merge was performed. The PDF/Docling comparison is a separate
experiment and is not represented by these parser acceptance results.

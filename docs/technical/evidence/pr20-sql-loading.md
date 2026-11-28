# PR 20 SQL loading evidence

Measured on 2026-11-28 against an isolated PostgreSQL 17 tmpfs database and local
fake LLM. No production data or paid LLM calls were used. Changes are layered on
PR 20 base `269626a` plus the data-packaging B+C/tail corrections and parser work.
[Recorded query measurements](pr20-sql-loading.json) preserve the raw before/after
counts. No schema migration or persisted payload format change is required.

## Behavior and measurements

Extraction now looks up and validates one requested part by run and part ID.
Already persisted parts skip model invocation; neighboring result payloads are not
loaded for the membership check. The task ownership check and typed corruption
failure remain. A mismatched stored part ID is rejected. Saving a new part retains
the run-row lock and atomically updates progress using a server-side aggregate of
unique fragment identifiers. Replaying a part retains its original payload and
exact unique coverage count. Final merge/reverification and tolerant corrupted
part recovery still use the existing full-result read path.

Clarification reads retain the original links and linked revision boundaries,
load their revisions together, then join applicable decisions and optional risks
in one query. Per-question decision revision order and the existing link order
are retained. Missing revisions still fail explicitly; all snapshots still pass
the same typed decoding boundary. Requirement/source overrides from each link
and application of the matching current decisions are unchanged. No command or
lifecycle semantics were changed.

| Same input/operation | Queries before | Queries after | SELECT records before | SELECT records after |
| --- | ---: | ---: | ---: | ---: |
| Save after 10 persisted parts | 5 | 4 | 13 | 2 |
| Replay after 2 persisted parts | 5 | 3 | 5 | 2 |
| Find one part among 10 | 2 | 2 | 11 | 2 |
| Read 1 question/decision/risk | 8 | 6 | 8 | 6 |
| Read 20 questions/decisions/risks | 84 | 6 | 103 | 63 |

The ten-part fixture contains 20,000 original/normalized requirement text
characters per prior part. Both implementations return the same part/progress and
all twenty questions, twenty decisions, and twenty risks. The legacy lookup row
was measured using the unchanged `parts()` API in the same comparison test.
Empty clarification state uses four queries and skips the decision query.

Counts come from SQLAlchemy `after_cursor_execute`: query counts include all
statements inside each operation; SELECT record counts sum the cursor row counts.
They measure database result rows, not table pages scanned or domain object count.
Joining a decision and risk returns one SQL row containing both objects. The
progress aggregate still requires PostgreSQL to read/parse old JSON internally;
it avoids transferring and validating all prior candidate payloads in Python.
A future normalized identifier index could reduce that remaining server work.

## Regression and validation

Before implementation, new assertions exposed bulk part reads on save and replay,
missing keyed lookup, and 84 queries for twenty clarification questions. A first
SQL fallback used a JSON string containing `[]`; malformed-input regressions
caught its PostgreSQL scalar-array error. The final fallback uses
`jsonb_build_array()` and reports malformed fragment identifier data through
`StoredExtractionCorrupt`, without reporting complete coverage.

The focused suite covers task isolation, keyed corruption checks, replay with a
different proposed payload, shared/duplicate identifiers, empty parts, malformed
array shapes/items, full question/decision/risk counts, linked revision bounds,
and missing linked revision failures.

- Focused integration suite: **14 passed**, 2.52 s.
- Clean unit and quality suites: **359 passed**, 38.90 s.
- Full isolated integration suite: **265 passed**, 139.54 s.
- Strict Mypy source/tests/helpers/tools: **passed**, 265 files.
- Configured Ruff all source/tests/helpers/tools: **passed**; formatting: **passed**.
- Changed SQL source/tests Pylint: **10.00/10**; cognitive complexity: **passed**.
- Architectural import contracts: **4 kept, 0 broken**.
- Bandit source and tests/helpers/tools: **passed** (existing unused `nosec B104`
  notice in the container composition file).
- `git diff --check`: **passed**.

An earlier mixed-environment `pytest backend/tests -q` run had **621 passed,
2 failed**. The failures were `test_settings.py` cases for YAML model precedence
and secret-file/environment conflicts: the integration command had injected the
fake model and database password into environment variables. Running unit/quality
with a clean SAA environment and integration against the isolated test runtime
keeps those configuration tests independent. No settings tests were weakened.
An intermediate integration run had **260 passed, 2 failed** on the malformed
fallback cases; those were fixed and the focused malformed-data cases now pass.

Commands use `uv run --locked --project backend pytest` with
`backend/tests/unit backend/tests/quality` in the clean environment and
`backend/tests/integration` with the isolated database/fake LLM settings. SQL
measurements can be emitted by setting `CODEX_SQL_EVIDENCE` to a JSON output path
while running `backend/tests/integration/test_sql_loading_efficiency.py`.

## Integration notes

The SQL patch changes only extraction store/protocol/part lookup, the clarification
read path, its new progress-query helper, regressions, and this evidence. It was
exported relative to a temporary Git index/tree after layering prior corrections;
those prior patches are excluded. It does not replace lifecycle changes to the
clarification view constructor or question-saving semantics.

The independently prepared lifecycle DI increment replaces the part extractor's
budget provider. When combining the extract-method hunk, preserve that injected
budget builder/constructor; the required lookup change is `get_part()` and the
early return for an already validated result. No budget/reserve behavior is part
of this SQL optimization. No commit, push, or merge was performed.

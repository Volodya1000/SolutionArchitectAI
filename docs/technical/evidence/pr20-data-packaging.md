# PR 20: test-image packaging and persisted extraction reads

Worktree: `D:/Codex/worktrees/pr20-data-packaging-fix`.
Base: `269626a7d3b88293624a419e3ff56983429b9d66`.
Branch: `codex/pr20-data-packaging-fix`. No commit, push, or merge.
The supplied `pr20-store-scopes` worktree was dirty and was preserved.

## Changes

- The Docker `test` stage includes `backend/test_helpers` and `tools`, and runs
  from `/app`. The runtime `base` stage does not copy these test dependencies.
- Clarification operation results are validated inside the persistence store;
  corrupt JSON returns HTTP 500 with `code=stored_extraction_corrupt`.
- Persisted question links enforce the question model's nonempty requirement-ID
  constraint before either preflight or direct answer writes a decision.
- Pending selection validates full question snapshots and saved statuses in one
  batch. Invalid or missing questions block their own waiting run; an unrelated
  queued run still executes. The partial object `{"blocking":false}` is covered.
- Implicit default history, explicit task-ID history, and commands written before
  history fields existed resolve to the same task-scoped identity. New, selected,
  and foreign-task histories remain separate. New-history commands still reject
  an explicit history ID.
- Summaries and detail responses expose `pipeline_versions` (saved) and
  `current_pipeline_versions`. Both contain nullable version strings for extraction
  prompt/contract, clarification prompt/contract/review, structured instructions,
  and extraction context. Unknown legacy versions stay null. Recorded clarification
  metadata overrides the start snapshot, including old `clarify-3` values.
- `configuration_current` and `current_completed` require every saved version and
  the model profile to match. Summaries still project metadata in PostgreSQL;
  requirements and result blobs are not transferred for these reads.

## Reproduction and test-first evidence

The unchanged Docker test image collected 297 tests and raised 11 collection
errors for missing `backend.test_helpers` and `tools`. Import-linter failed with
`No module named 'backend'`. After the packaging change, an image without bind
mounts collected 596 tests and kept all four import contracts.

The persisted-data regressions first produced **6 failed, 4 passed**. The failures
were an incomplete question object, empty requirement links through three read
paths, and malformed/invalid saved operation results. After the fixes these ten
cases passed. History/legacy-version regressions first produced **7 failed,
2 passed**; recorded-metadata precedence produced two further expected failures.
The invalid new-history/default-ID combination produced one expected failure
before its guard was restored.

The latest focused browser/persisted-data run completed **47 passed, 0 skipped**.
A broad run completed **594 passed, 1 failed, 0 skipped**: the failure was
`test_settings.py::test_nested_secret_file_is_loaded_and_conflicting_env_is_rejected`.
The combined run inherited the disposable database password environment variable,
which deliberately conflicts with this test's file-secret scenario. Following the
quality runner's separate environment policy, the clean unit/quality rerun passed
**346 tests, 0 skipped** and the own-database integration rerun passed **251 tests,
0 skipped**. Together they cover all **597 tests** after the final guard regression.
The contaminated combined command is retained here as a failed invocation.

Ruff, Ruff formatting, Mypy (261 files), Pylint (10.00/10), Bandit, and WPS231
checks passed after the focused changes. Bandit printed its existing B104
suppression warning for `di/container.py`. Full application quality, frontend,
real-model semantic acceptance, and demo-volume checks were not run by this scope.

## Commands

Run import-linter from the repository root. Standalone invocation from `backend`
without configuring the repository root on Python's import path is unsupported.

```powershell
uv run --locked --project backend lint-imports --config backend/.importlinter
uv run --locked --project backend python -m pytest backend/tests/unit backend/tests/quality -q
uv run --locked --project backend python -m pytest backend/tests/integration -q
docker build -f backend/Dockerfile --target test -t saa-pr20-data-packaging:final .
docker run --rm saa-pr20-data-packaging:final python -m pytest backend/tests --collect-only -q
docker run --rm saa-pr20-data-packaging:final lint-imports --config backend/.importlinter
```

The integration command uses only Compose project `saa-pr20-data-packaging`,
its `solution_architect_test` database on tmpfs, and its fake LLM. Demo projects
and their volumes were not changed. No paid LLM calls were made.

The tiny local `structured_prompt.PROMPT_VERSION = "structured-2"` insertion is
excluded from the exported patch because the parent agent supplies it.

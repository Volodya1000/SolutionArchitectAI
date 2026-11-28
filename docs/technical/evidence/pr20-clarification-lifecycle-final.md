# PR 20 clarification corrections: final backend verification

Isolated worktree: `codex/pr20-clarification-lifecycle-fix`, base `269626a7d3b88293624a419e3ff56983429b9d66`. The pre-existing dirty UX review worktree was preserved. No commits, pushes or merges.

## Final commands and exact results

- Clean SAA environment: `uv run --locked --project backend python -m pytest backend/tests -m 'not integration' -q -o faulthandler_timeout=60`: **382 passed, 207 deselected**, **589 collected**, **0 skipped**, 41.57 seconds.
- Own PostgreSQL/fake environment: `uv run --locked --project backend python -m pytest backend/tests/integration -q -o faulthandler_timeout=60`: **235 passed**, **235 collected**, **0 skipped**, 156.88 seconds. This directory includes 28 unmarked adapter tests also present in the first command; the two successful commands cover all 589 distinct collected backend tests.
- `uv run --locked --project backend python -m mypy --config-file backend/pyproject.toml backend/src backend/tests backend/test_helpers tools`: **277 source files passed**.
- Configured Ruff on the same targets: **passed**. Configured formatting: **280 files already formatted**.
- `uv run --locked --project backend python -m flake8 --config backend/.flake8 backend/src backend/tests backend/test_helpers tools`: **passed**.
- Changed workflows/provider/helpers/durable tests Pylint: **10.00/10**. This is scoped Pylint evidence, not a claim that every repository gate was executed here.

Earlier red runs and corrected failures are retained in the preceding evidence files: missing same-gap bindings; missing mandatory diagnostic with empty questions; assumption dead end; repeated validated review requests after crash; false category-only mandatory classification; scheduler starvation from a failed completed continuation; stale tests mutating the removed policy setter. The final runs above include their fixes.

## Delivery order

1. `clarification-lifecycle.patch`: initial merge and lifecycle corrections.
2. `history-window-splitting.patch`: recursively split source/requirements while retaining one historical record; reserve actual correction diagnostic context.
3. `durable-review-conflicts.patch`: validated per-window question, evidence and assessment replay; independent conflict provenance; compatible migrations 0008 and 0009.
4. `continuation-failure.patch`: acknowledge a failed completed continuation only at its captured resume revision, preserve prior completed result, record diagnostic, allow queued neighbors.
5. `direct-dependencies.patch`: directly injected workflow collaborators, shared budget builder and no synchronizing policy setter; additional cache corruption/scope/request-count tests.
6. `root-direct-dependencies.patch`: read-only-root-compatible replacement for the two conflicting workflow/extractor hunks in step 5. Preserves root review prompt version metadata and SQL keyed part lookup. `git apply --check` against the root's observed files passed. Parent applies this instead of those two step-5 files.

The initial category-only fallback described in the first evidence file was superseded by independent candidate/confirmed/refuted assessment. A verified citation alone does not prove a mandatory conflict. Existing saved established mandatory-conflict audit remains authoritative. SourceRef and public command payloads remain compatible.

Only own Compose project `saa-quality-clarification-lifecycle` was used, with databases `solution_architect_test` and `solution_architect_continuation_test`, loopback ephemeral ports and own project volume. No developer demo database or volume was used. No real paid model requests. Controlled models prove workflow and persistence behavior; real-model semantic acceptance and integrated frontend/full gates belong to the parent task.

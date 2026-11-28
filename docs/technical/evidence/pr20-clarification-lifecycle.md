# PR 20 clarification lifecycle corrections

Base: `269626a7d3b88293624a419e3ff56983429b9d66`.
Worktree: isolated `codex/pr20-clarification-lifecycle-fix`; original dirty UX worktree preserved.

## Regression evidence

Before implementation, `uv run --locked --project backend pytest backend/tests/unit/test_pr20_question_merge.py -q`: **3 failed**, all on missing requirement bindings in A/B, B/A, A/B/A orders.
Before implementation, `uv run --locked --project backend pytest backend/tests/integration/test_pr20_conflict_recovery.py -q`: **3 failed**: valid empty question response lost proven conflict; pending and confirmed mandatory assumptions rejected factual correction as stale.

Post-fix targeted merge: **3 passed**; initial lifecycle PostgreSQL: **3 passed**. Expanded targeted lifecycle/worker run: **13 passed, 1 failed** because test answer helper duplicated source versions for two fragments from one immutable version. Helper now deduplicates versions; worker conflict suite rerun: **5 passed**.

## Verification

- Full backend initial command with integration SAA environment: **566 passed, 3 failed**, no skips, **569 collected** at that point. Failures: Pylint quality probe exceeded its 30-second child-process timeout; `test_nested_env_overrides_yaml_without_reading_developer_dotenv` saw injected fake-chat model; `test_nested_secret_file_is_loaded_and_conflicting_env_is_rejected` correctly rejected injected database password plus secret file.
- Clean process environment, `uv run --locked --project backend python -m pytest backend/tests -m 'not integration' -q -o faulthandler_timeout=60`: **380 passed, 195 deselected**, no skips, **575 collected**. Includes quality Pylint probe and both settings tests passing.
- Own integration environment, `uv run --locked --project backend python -m pytest backend/tests/integration -q -o faulthandler_timeout=60`: **223 passed**, no skips, **223 collected**. Directory invocation intentionally includes existing unmarked adapter cases.
- `uv run --locked --project backend python -m mypy --config-file backend/pyproject.toml backend/src backend/tests backend/test_helpers tools`: **passed, 263 source files** at verification time.
- Ruff configured with `--config backend/pyproject.toml`: all repository targets passed after sorting five changed-file import blocks; formatter: **266 files already formatted**. Earlier invocation without explicit config applied different settings to tools and reported 38 diagnostics; it was not the repository gate.
- No real paid API requests or model-quality claims. Full frontend/full repository gate belongs to parent integration.

## Runtime isolation

PostgreSQL and fake model use only Compose project `saa-quality-clarification-lifecycle`, fresh project-prefixed PostgreSQL volume, database `solution_architect_test`, loopback ephemeral ports. Migrations and checkpoint setup ran on that database. Developer demo services and volumes were not modified. Initial uv build failed on the inherited unavailable proxy, then succeeded with proxy variables cleared for that process.

## Behavior

Same-gap windows merge requirement bindings, verified sources, reasons, blocking and mandatory-conflict evidence deterministically. Newest revision wins status decisions; repeated windows are idempotent. Saved answer is applied to all bound requirements, excluding unrelated requirements.

Proven persisted contradiction candidates always receive a blocking diagnostic even if model returns valid `questions: []`. Completion and explicit resume reject an uncovered persisted contradiction. A false question refuted by selected source evidence can complete.

A mandatory-conflict assumption can receive a factual correction in the same run; server creates the next question revision and retains old assumption, risk and command replay. Confirmation of such an assumption reopens a factual question rather than leaving a closed risk with no action. Previously persisted confirmed/closed/assumed waiting states accept the same correction. Ordinary assumption confirmation/rejection remains covered by existing integration suite.

Public request/response models and SourceRef are unchanged. No database migration is needed. Durable per-window model replay is a separate follow-up scope.

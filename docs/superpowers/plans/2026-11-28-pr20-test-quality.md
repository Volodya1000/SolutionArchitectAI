# PR20 test quality implementation plan

**Goal:** Improve regression detection and refactoring resistance in PR #20 without merging it.

**Scope:** The user's approved testing-quality brief, applied to the current
`75ad38f19138632dd78485faad436f44b385a3db` baseline. Earlier application/model
acceptance remains separately reported in the existing acceptance checklist.

**Architecture:** Keep pure transformations fast; exercise persistence with real
PostgreSQL and SDK adapters with controlled HTTP transports. Extend the existing
quality runner and lint configurations rather than introducing another pipeline.

**Execution:** Sequential in the existing PR worktree, as explicitly requested.
No intermediate approval or merge. Preserve strict annotations and coverage floors.

## Tasks

- [x] Record baseline collection, coverage and gate duration. Read the testing
  notes at `de613d951f73f017f92f93509957b3e82d6ca0e1` and audit the current suites.
- [x] Strengthen independent requirement/role/route/SSE expectations, replace path
  identity with value equality, and run reversible mutations before and after.
- [x] Replace SQLAlchemy session mocks with PostgreSQL corruption scenarios;
  verify fresh reads, isolate database state and exercise reordered collection.
  Replace checkpoint structure assertions with recovery and durable-result checks.
- [x] Remove proxy dependence from SDK transport tests and include them once in
  fast/full. Preserve real SDK serialization, retries, cancellation and no network.
- [x] Strengthen equal-sequence frontend regression; replace DOM/cache assertions
  with user-facing behavior and replace matching business logic with explicit MSW
  scenario responses. Exclude test support from production coverage.
- [x] Add product/test import boundaries, targeted Ruff SLF001, a small typed AST
  session-mock check and test-specific ESLint rules, including rejection probes.
- [x] Document the principles and concrete examples in English, update Unreleased
  and the existing checklist, and publish reproducible mutation/audit evidence.
- [ ] Run all fast/full gates and pre-commit, review the final diff, commit logical
  groups, push the existing branch, update PR description and wait for Actions.

## Review focus

- Missing, duplicate and misassociated requirement records must fail independently.
- Validation must identify the target field through production route registration.
- Heartbeats must keep an unchanged stream alive until a later terminal snapshot.
- Independent database transactions must retain real commit/locking semantics.
- HTTP/SSE races and equal sequence events must preserve the visible newest text.
- Test support imports and SQLAlchemy mock aliases must be caught without banning
  legitimate external adapters or SQLAlchemy parsing tests.

## Evidence

Commands, outcomes and limitations are recorded in
`docs/technical/pr20-test-quality.md`; temporary defects must never be committed.

Implementation and local verification completed at `325bd28acd96441298989cc5d895197cf0ad67de`. The final
publication/Actions task is tracked in PR #20 after this plan snapshot is committed.

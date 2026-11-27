# PR 2 code review implementation plan

The user authorized style corrections and fixes for verified logic problems in the
attached review. Existing uncommitted PR 2 changes must be preserved. Do not merge
or publish. Use uv and pnpm 12; retain explicit backend annotations.

## Agreed decisions

- Preserve original-file integrity verification even on a parsed-document cache hit.
- Preserve mandatory explicit local annotations, as confirmed by the user.
- Keep application orchestration separate from persistence repositories.
- Preserve strict JSON validation, immutable publication and bounded token budgets.

## Implementation

- [x] Add regression tests for invalid policies, multipart context reuse, independent
  recovery failures, worker concurrency and corrupt-run isolation.
- [x] Group application models, errors, prompts, protocols, agents, context, services
  and workflow phases; update imports, dependency injection, tests and documentation.
- [x] Make document-service names explicit, extract digest helpers and reuse verified
  version loading. Isolate expected recovery errors and avoid a redundant query.
- [x] Separate context identity and response estimation; use typed payloads and avoid
  repeated growing-prefix tokenization. Preserve exact final budget checks.
- [x] Split workflow preparation, part processing and finalization; cache context only
  for an active execution and discard it on completion, failure or cancellation.
- [x] Extract structured validation and one-attempt invocation; keep strict JSON semantics.
- [x] Extract document validation, reuse decoded text and Markdown parser, and harden
  heading handling. Review local storage integrity and cancellation behavior.
- [x] Use typed graph node names/state, explicit DI names and AsyncGenerator annotations.
- [x] Record naming preferences in AGENTS.md and changes under Unreleased.
- [x] Run fast/full quality checks, inspect the final diff and write a review checklist
  explaining accepted, rejected and conditional suggestions with verification evidence.

## Review focus

- Cached parses must still detect corrupt source files.
- Context reuse must never mix runs, profiles, scopes or resumed process state.
- One damaged run or failed upload must not stop independent work.
- Cancellation and retries must preserve budgets, terminal states and resource cleanup.
- Refactoring must retain saved snapshots and checkpoint compatibility.

## Review ledger

- Baseline: 201 unit tests passed; pre-existing dirty edits saved and preserved.
- Added regressions exposed policy validation, repeated prefix tokenization,
  malformed heading handling, binary format detection and late concurrent save.
- Independent read-only review found loss of final original-file validation with
  cached context. Regression reproduced an incorrect COMPLETED result; finalizer
  now rechecks files without rebuilding the pack.
- Confirmed cancellation validates both domain stages and persists one final update.
- Independent review of the final delta found no remaining important issues.
- Full gate passed: 235 fast Python checks, 16 gate probes, 53 frontend tests,
  89 integration tests, 14 browser tests, dependency audits, build and restart/failure smoke.
- Backend coverage: 93.73%. After local loop-annotation additions, backend static
  and all 224 unit tests passed again. Source loop annotation audit found no gaps.
- Initial Windows report/build output permission failures were resolved by removing
  only generated coverage/dist/browser outputs; no hooks or checks were disabled.

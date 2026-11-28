# Store errors and test boundaries implementation plan

**Goal:** Keep SQL session scopes generic, classify failures at their real boundaries,
and prevent dependencies between collected test modules in PR 20.

**Architecture:** `SqlAlchemyStoreContext[StoreT]` owns transactions, cancellation
and availability failures. Persisted-data decoders own corruption errors. Integrity
and programming exceptions retain their SQLAlchemy types. Test fixtures use pytest
discovery; reusable constructors live in dedicated helper modules.

**Tech Stack:** Python 3.13, SQLAlchemy, psycopg, Pydantic, pytest, import-linter.

**Spec:** User request of 28 November 2026; repository AGENTS.md and quality plan.

## Constraints and review focus

- Keep explicit types, existing transaction timeout, rollback and cancellation.
- Never classify input ValidationError as persisted-data corruption.
- Do not classify deadlocks, integrity or programming failures as availability.
- Cover corrupt persisted records in documents, extraction, clarification and chat.
- Test import rules must include future files and indirect dependencies.
- Preserve prompt meaning and version its changed model instructions.
- No merge; leave a working local application with verification evidence.

## Tasks

- [x] Add failing regression tests for exception identity, SQL classification and
  rollback; remove Enum dispatch and update DI/test setup.
- [x] Add persisted-data decoding tests; move corruption translation to explicit
  read boundaries in all affected stores, retaining corrupt-part recovery.
- [x] Move shared fixtures/helpers and enforce test-module independence using
  import-linter, including negative quality probes (delegated isolated worktree).
- [x] Consolidate clarification instructions into English, retain source-language
  human output and exact quotes, increment prompt version.
- [x] Run quality setup/full gates, PostgreSQL tests, browser tests, review diff,
  update CHANGELOG and leave a separate local demo runtime available.

## Execution record

- Working in existing PR worktree on `codex/pr3-clarifications`, base `e7fbfc0`.
- User supplied concrete design and requested autonomous implementation; no extra
  design approval round. Existing unrelated dirty worktrees remain untouched.

- Independent review found four important gaps: persisted status reads; mutable
  incoming preferences; alternate test import paths; SQL-side JSON casts. All
  accepted. Status/input regressions passed RED to GREEN; PostgreSQL regressions
  for corrupt summary and pending queries passed RED to GREEN (15 focused tests).
- SQL JSON projections retain bounded database reads and guard legacy TEXT JSON
  using PostgreSQL 17 validation; malformed question data blocks only its run.
- Import enforcement uses a custom import-linter contract beyond Grimp package
  discovery, covering pytest aliases, unpackaged folders and tools bridges.
  Its 26 negative/positive probes include execution from the backend directory.
- Ruling: keep integrity/programming/deadlock exceptions as their original types;
  only connection failures, pool timeout and expiry of this scope map to
  StorageUnavailable. A timeout raised by the caller remains unchanged.

- Final local verification: 315 fast Python checks (304 unit + 11 runner checks),
  42 quality probes, 217 PostgreSQL/adapter tests, 104 frontend tests and 30
  Playwright scenarios passed. Runtime restart/outage smoke passed. The one old
  expectation of raw saved-data ValidationError was updated to the new corruption
  contract, then all 217 integration tests were rerun successfully.
- Demo verified through visible UI controls and API: one run remains waiting for
  input; another completed after both independent source questions were answered.
  All 160 runtime Python source files match the worktree. Real LLM acceptance was
  not rerun, and the previous semantic blocker remains recorded.

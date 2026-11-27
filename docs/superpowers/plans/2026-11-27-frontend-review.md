# Frontend review fixes

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Address the supplied frontend review and push new commits to PR 16.

**Architecture:** Keep React, Query and the existing feature boundaries. Reconcile chat snapshots by run sequence; use guarded session storage for drafts and uncertain commands. Add compact bounded backend reads for document lists and extraction history/status.

**Tech Stack:** React, TypeScript, TanStack Query, FastAPI, SQLAlchemy, Vitest, pytest.

**Spec:** User-supplied frontend review, 27 November 2026; repository frontend and quality documents.

## Global constraints

- pnpm 12.21.0; uv for Python; no global cache changes.
- Preserve explicit backend annotations and architectural gates.
- Run fast commit and full push hooks; no merge.

## Review focus

- Delayed HTTP responses must preserve newer SSE text and terminal status.
- Storage exceptions must not block commands or turn success into failure.
- Reopened forms must recover the exact uncertain operation before retrying.
- Re-selected upload bytes must match the saved command.
- Active polling must avoid downloading entire result history.

## Tasks

### 1. Chat consistency and resilience

Files: chat stream, hooks, composer and regression tests; shared session storage adapter.

- [x] Reproduce delayed HTTP/SSE race and background failure with cached messages.
- [x] Reconcile HTTP and SSE snapshots at Query write time, retaining newer messages/runs.
- [x] Guard all session storage operations with memory fallback; test send and cleanup failures.
- [x] Extract composer and index runs by assistant message ID.
- [x] Run focused Vitest checks and commit with Unreleased changelog.

### 2. Recoverable document work

Files: document forms, draft and pending-command modules, workspace regression tests.

- [x] Reproduce loss across remount/reload and mismatched upload re-selection.
- [x] Persist task-scoped analysis draft and uncertain command descriptions.
- [x] Recover upload/extraction by operation ID before sending again; preserve identity on retry.
- [x] Verify SHA-256/name/size when the upload file must be re-selected.
- [x] Run focused regression tests and commit.

### 3. Bounded document and extraction reads

Files: backend document/extraction models, stores, services/routes/tests; frontend API/history/cards/results.

- [x] Backend agent implements latest version, compact paginated history, status and operation lookup in its own worktree.
- [x] Test lazy version histories, history pagination and active status reads.
- [x] Integrate backend patch; switch frontend to bounded reads and full detail on demand.
- [x] Run backend and frontend tests and commit.

### 4. Theme ordering and CSS boundaries

Files: theme provider/tests, styles and feature imports.

- [x] Reproduce concurrent theme PUT ordering; serialize writes and verify final server selection.
- [x] Split tokens/base, shared UI, shell and feature styles; use a shared surface class.
- [x] Scope global main/h1 styles to their intended application elements.
- [x] Verify formatting, lint, typecheck and browser acceptance.

### 5. Publish verified commits

- [x] Review combined changes, address findings and update documentation/changelog.
- [ ] Run complete quality gate without bypassing hooks.
- [ ] Push current PR branch and verify remote head and CI outcome.

## Execution decisions

The user authorized implementing all review fixes and pushing new commits. Continue in the clean existing PR checkout; backend work is isolated in a sibling worktree. The supplied review determines the correction design; no new product scope is added. Recommendations about future multi-task routing and virtualization remain future work.


## Verification record

- Independent review found an unresolved analysis retry incorrectly gated by the edited draft. The regression first failed, then passed after separating retry controls from draft/history state.
- The delayed HTTP/SSE regression was verified against the actual Query cache with the reconciliation disabled (failure) and restored (success).
- Combined code: 67 frontend tests; line coverage 94.72%, branch coverage 85.63%. ESLint, strict TypeScript and Prettier passed.
- Backend: 235 fast Python tests, 16 gate probes and 99 PostgreSQL integration tests passed; combined backend coverage 93.68%.
- Frontend architecture/type probes, production build, dependency audits, 14 Playwright scenarios and restart/database-outage smoke passed.
- The initial full command was interrupted at dependency audit because inherited proxy settings pointed to an unavailable endpoint. Audit and acceptance were rerun successfully with process-only proxy removal; global settings were preserved. The final pre-push hook runs the complete gate again against the committed revision.
- Backend commit: f95e3cc; its normal pre-commit gate passed. Frontend changes and this record are the next commit. Publication is tracked by the PR and the final chat result.

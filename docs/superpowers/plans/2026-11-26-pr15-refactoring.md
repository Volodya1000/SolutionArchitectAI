# PR 15 refactoring implementation plan

> Use superpowers:executing-plans and superpowers:test-driven-development.

**Goal:** Address the supplied PR review without weakening idempotency,
history consistency, cancellation or repository quality gates.

**Architecture:** Keep the existing application ports and React external-store
runtime. Associate each assistant message with its persisted run. Recover SSE
with delayed reconnects and authoritative history reads. Keep SQL transaction
ownership in the factory and status decisions in the domain.

**Tech stack:** Python 3.13 / uv, FastAPI / Pydantic / SQLAlchemy / PostgreSQL,
React / assistant-ui / TanStack Query / Zod, pnpm 12.21.0, Compose.

**Spec:** User review supplied in the chat on 26 November 2026; frontend and
quality contracts in `docs/technical/frontend.md` and `quality-and-testing.md`.

## Constraints and decisions

- Work on the existing clean PR branch; do not merge.
- Preserve the locked versions and the developer's global package stores.
- Reuse production Zod schemas in browser helpers instead of duplicating DTOs
  or introducing an array-only type guard that does not validate its elements.
- Keep the lost-response test: `route.fetch()` confirms server acceptance before
  the browser response is discarded. Add a distinct pre-delivery failure case.
- Preserve the single-statement message/run snapshot; separate reads would
  reintroduce the previously fixed consistency race.
- Keep independently pinned Python and uv images: Astral documents this pattern.
- Configure published host bindings separately from container listener ports.

## Review focus

- A draft edited while a retry is in flight survives its acknowledgement.
- Malformed stream JSON must recover rather than escape the event handler.
- A terminal history read clears a connection warning without another event.
- Cancellation wins over a late worker completion without advancing sequence.
- A stale schema fails readiness; the current migration head succeeds.

## Task 1: User-visible chat defects and browser test readability

Files: `frontend/src/features/chat/{chat,messages,use-chat}.tsx/ts`,
`frontend/src/shared/api/client.ts`, chat tests and `frontend/e2e/` helpers.

- [ ] Add and run failing regression tests for per-message incomplete status,
  edited retry drafts, closed SSE after 503, terminal history recovery, and
  oversized input / HTTP 422 preserving the draft.
- [ ] Carry run status through message metadata; render it at its answer.
- [ ] Clear composer/storage only if they still represent the acknowledged text.
- [ ] Reopen a failed stream after a delay; refresh history during recovery,
  stop on terminal state, and clean up timers/connections when leaving the chat.
- [ ] Show the 16,000-character limit and a useful validation error, including
  server-side validation. Count Unicode code points consistently with Python.
- [ ] Extract semantic locators, labels, polling and validated API helpers.
  Verify message order, run counts and actual progress after reconnect.
- [ ] Run Vitest, frontend gates and real-browser regressions; commit.

## Task 2: Typed SSE protocol

Files: application contracts, presentation routes, SSE unit tests.

- [ ] Test the actual emitted envelope and SSE data/comment framing.
- [ ] Add `RunSnapshotEvent` with literal kind and `RunView` payload.
- [ ] Serialize through Pydantic and extract frame formatting helpers.
- [ ] Run backend unit/static gates; commit.

## Task 3: SQL repository contracts and consistency

Files: persistence queries/store/factory/models/migrations, domain runs,
application ports/service, DI and backend tests.

- [ ] Add failing tests for bounded pending-query count, task scope, unlocked
  preference reads, one-run-per-answer, readiness and transition race handling.
- [ ] Rename implementation to `SqlAlchemyStore`; scope create/list/chat
  consistently through a constructor task ID with the local default.
- [ ] Fetch pending runs with one JOIN and build views from already loaded rows
  after writes; retain fresh reads where concurrency requires them.
- [ ] Separate preference reads and writes; lock only writes.
- [ ] Centralize idempotent/cancellation precedence policy in the domain while
  retaining strict invalid-transition validation.
- [ ] Add an Alembic unique constraint on `runs.assistant_message_id`.
  Existing `(chat_id, position)` uniqueness stays in place.
- [ ] Compare schema revisions against migration heads, report storage/schema
  unavailability explicitly, and preserve coherent JOIN snapshots.
- [ ] Run PostgreSQL integration, unit/static gates; commit.

## Task 4: Runtime configuration and final checks

Files: backend launcher / Dockerfile, Compose, `.env.example`, runtime docs.

- [ ] Read backend listener host/port from environment in a Python launcher.
  Parameterize Compose published bindings and propagate the listener port to
  health checks and the frontend proxy.
- [ ] Build and test defaults plus overridden ports; update runtime instructions.
- [ ] Run workflow-equivalent backend/frontend/repository checks, Playwright
  and restart/failure smoke with fake LLM; preserve the PDF workflow.
- [ ] Request an independent whole-change review, address material findings,
  and report a completed/deferred/disagreed checklist and exact test results.

## Execution record

- Baseline: 8 Vitest tests and 28 non-PostgreSQL pytest tests pass.
- Docker Desktop started; existing PostgreSQL and fake-LLM services are healthy.

- Task 1: 16 Vitest and 11 Playwright tests pass (installed Edge channel;
  bundled Chromium was absent). ESLint, TypeScript, Prettier and Vite build pass.
- Task 2: typed event regression RED (missing contract), then GREEN; existing
  Unicode/newline SSE framing and heartbeat tests pass.

- Task 3: PostgreSQL regressions RED confirmed N+1, read locks, duplicate answer
  association, stale-schema exception and redundant SELECT. After migration and
  fixes, the complete backend suite passed: 61 tests with network restrictions.
- Task 3 ruling: retain strict `transition`; `resolve_transition` owns replay and
  cancellation precedence in the domain. The store contains no transition policy.

- Task 4: all 65 backend tests and static gates pass. Compose built and became
  healthy both with defaults and with backend listener 18010 / published 18000,
  nginx listener 18081 / published 18080. On overridden ports, 11 Playwright
  tests and complete restart/database-failure runtime smoke pass.
- Extra regression: Enter during an in-flight retry issued a third command
  despite the disabled button (RED). Guarding keyboard submission fixed it;
  all 18 frontend tests pass, including 16,000 emoji at the length boundary.
- Documentation validation needs the separately declared jsonschema dependency
  and an LF Git export on Windows; full publisher tests additionally need Pandoc.

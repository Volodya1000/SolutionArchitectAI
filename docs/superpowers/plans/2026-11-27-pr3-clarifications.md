# PR 3 Clarifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver durable clarification, scoped discussion and explicit human decisions in the existing requirements workflow, then open a separate PR to main.

**Architecture:** Extend the existing StateGraph and PostgreSQL stores. Preserve original extraction snapshots; store question revisions, decisions, requirement additions and assumption risks transactionally. Discussion context is assembled by the server from a pinned subject and an optional explicit analysis.

**Tech Stack:** Python 3.13, uv, FastAPI/Dishka, SQLAlchemy/PostgreSQL/Alembic, LangGraph AsyncPostgresSaver, React/TypeScript, pnpm 12.21.0, TanStack Query, Vitest/Playwright.

**Spec:** [approved design](../specs/2026-11-27-pr3-clarifications-design.md), approved 27.11.2026 with four additional acceptance conditions below. Execution through implementation and PR is already authorized; no additional plan approval is required.

## Global Constraints

- Existing extraction, chats, immutable sources and operation recovery must remain compatible.
- SQL UoW is short lived; no transaction or generation slot remains held while a human thinks.
- Explicit Python annotations, including locals and attributes; no application `Any`.
- Frontend uses pnpm 12.21.0 and its committed lockfile; no global cache/store changes.
- Source PDFs and original reporting-system.md remain unchanged; no R-04-specific production logic.
- No merge; model/Git publication belongs to 4A/4B, graphical editing to stage 5.

## Review Focus

1. Answer vs assumption with different operation IDs races on the same revision: one commit, one 409, no loser effects (Task 1).
2. Two independent blocking questions: first answer immediately updates its requirement while the second remains open; global completion waits (Tasks 1/3/5).
3. One fragment, two analyses with different histories: explicit analysis selects its history; direct source discussion receives none (Task 4).
4. Reject assumption after END: preserve completed cycle, history and rejection reason; new question revision and clarification cycle on the same thread, no extraction (Tasks 1/3).
5. Crash between SQL commit and checkpoint, stale browser and retries: durable resume intent, immutable result replay, no second decision/risk (Tasks 1/3/5).

## Task 1: Transactional decisions and working requirement revisions

**Files:** Create `domain/clarifications.py`, `application/models/clarification_models.py`, `application/protocols/clarification_protocols.py`, `application/services/clarification_service.py` under the backend package; create focused models/store/factory/command modules in `persistence/clarifications/`; migration `0006_clarifications.py`; routes `presentation/clarification_routes.py` and DI `di/clarifications.py`. Modify extraction DTOs/store/query presentation and register the new schema/provider/router.

**Interfaces:** `ClarificationStoreFactory.open()` yields a scoped store. `ClarificationService.answer(run_id: UUID, question_id: UUID, command: AnswerClarification) -> DecisionResult`; `resume(run_id: UUID, command: ResumeRun) -> CommandResult`; `resolve(assumption_id: UUID, command: ResolveAssumption) -> DecisionResult`; `get(run_id: UUID) -> ClarificationView`. DTOs carry expected question revision, exact version/hash set and operation ID. `ActorContext` is supplied by trusted DI, never request author fields. Command lookup returns a detached persisted result.

- [ ] Write `backend/tests/integration/test_clarification_commands.py`: use real PostgreSQL and independent sessions, synchronize answer and assumption commands with different operation IDs against one question revision. Assert exactly one DecisionResult, one Conflict, one decision, at most one assumption/risk, one requirement addition, one durable resume intent; replay winner returns byte-equivalent result. Repeat both winner orderings.
- [ ] Add stale revision, changed payload, foreign task, read-only author, cancellation race, source-set mismatch and rollback tests. Add two-question test: after first answer its effective requirement already contains the human addition; other question is open and run is waiting.
- [ ] Run targeted tests and observe missing functionality (RED).
- [ ] Implement row-lock/CAS on the question revision plus a unique decision revision constraint. Operation lock/replay precedes freshness checks after access verification; any failed command rolls back all effects. A persisted effective-view overlay preserves original_text/sources. Assumption acceptance atomically creates A-01/A-07; rejection appends history, opens a new question revision and records a new clarification cycle without overwriting the completed cycle.
- [ ] Test and implement scoped history groups (`reuse` default, explicit `new`); include history semantics in command digests and matching analysis lookup. Validate UUID/enum boundaries and meaningful 409/403 codes.
- [ ] Run targeted integration tests (GREEN), Ruff/Mypy, then `quality fast`; commit the task when the gate passes.

## Task 2: Clarification agent and source verification

**Files:** Create `application/agents/clarification_agent.py`, `application/prompts/clarification_prompt.py`, `application/context/clarification_context_builder.py`; extend clarification DTOs/protocols/DI and `tools/fake_llm/server.py`.

**Interfaces:** `ClarificationAgent.clarify(context: ClarificationContext, budget: ExecutionBudget) -> ClarificationSet`. Context contains selected source fragments, requirements, history questions/answers, and prompt/profile versions. `ClarificationWorkflow.prepare_questions(run_id: UUID) -> None` saves validated results idempotently. Application assigns question UUIDs; the agent references stable existing gap keys and typed source evidence.

- [ ] Write `backend/tests/unit/test_clarification_agent.py`: false extracted gap rejected by full source context, closed gap paraphrase stays closed, changed basis yields explicit revision/diff, invalid dependent IDs and fabricated citations rejected, unrelated histories excluded, untrusted input stays user data. Observe RED.
- [ ] Implement source review across selected fragments, strict references and bounded structured generation through the existing generator. Persist result before graph advances. Oversized context returns a typed limitation; never silently omit decisive evidence. Semantic absence is assessed by ClarificationAgent, not by hash comparison.
- [ ] Add fake schema routing/controls for blocking, nonblocking, two independent gaps and failures; test fixtures may know the reporting example, production code must not. Run targeted tests (GREEN) and the fast gate; commit.

## Task 3: Interrupt, partial progress, resume and completed-cycle re-entry

**Files:** Modify `infrastructure/extraction_graph.py`, `application/workflows/extraction_{finalizer,worker,part_extractor,steps}.py`, extraction store/protocol/models; create `application/workflows/clarification_workflow.py` and focused budget persistence helpers.

**Interfaces:** Existing `ExtractionGraph.run(run_id: UUID) -> None` remains. Graph nodes load durable decisions via workflow; interrupted invocations use `Command(resume=decision_refs)`. GraphState adds compact cycle/reference fields. `save_candidates()` is idempotent and distinct from `complete()`. Budget reads a persisted active interval with lease/heartbeat; request counters remain cumulative.

- [ ] Add `backend/tests/integration/test_clarification_graph.py`: two independent blockers, first answer visible before second; no dependent completion while open; second answer completes; nonblocking question completes immediately. Observe RED.
- [ ] Add crash after SQL answer commit before checkpoint, crash before interrupt checkpoint, duplicate worker delivery, restart waiting, cancellation and post-resume failure. At concurrency=1 a waiting run must release SQL transactions, context and capacity so chat can execute. Simulate next-day wait without spending active budget.
- [ ] Add a distinct completed-result test: accept assumption, complete cycle 0, reject with reason, retain completed cycle snapshot and prior decision, open question revision 2 in cycle 1 on same thread; answer again and finish cycle 1. Count extraction calls/requirement UUIDs to prove no second extraction. Do not model this as `Command(resume)` against END.
- [ ] Implement graph extension, durable resume delivery and startup reconciliation. First answers apply transactionally even if graph remains interrupted for other blockers. On END re-entry pass new compact cycle input and route directly to clarification processing. No external next-stage state machine. Keep legacy completed threads readable.
- [ ] Run all graph/extraction lifecycle tests, backend suite and fast gate; commit when green.

## Task 4: Durable discussions with explicit context scope

**Files:** Create discussion DTOs, context builder, service, store/protocol and presentation route modules; extend ChatView/ChatSnapshot and chat worker context construction/DI, migrate discussion binding and operation records.

**Interfaces:** `DiscussionService.start(command: StartDiscussion) -> ChatView`; `DiscussionContextBuilder.build(chat_id: UUID) -> list[MessageView]` returns bounded trusted-wrapper/untrusted-source messages. Source subject has version/fragment/locator and optional `analysis_id`; requirement subject has run/requirement. Analysis must own that version and is the only route to answer history. No analysis means source-only context.

- [ ] Write `backend/tests/integration/test_discussions.py`: one fragment in analyses A/B with different answers; bound discussion A includes only A, B only B, direct document discussion includes neither. Foreign analysis/version rejected. Observe RED.
- [ ] Test each intentional start creates a new chat, operation replay returns same chat, changed payload conflicts, old chat after new upload still references v1/locator, unavailable source reports reason. Ordinary chats remain unchanged.
- [ ] Implement subject binding/history/operation in one SQL transaction, server-assembled context and verifiable source links. Respect context budget including source messages; generation has no answer-command capability. Run targeted and chat regression tests and fast gate; commit.

## Task 5: Requirements, source and chat UI

**Files:** Extend `frontend/src/shared/api/{extractions,client,documents}.ts`; create clarification/discussion API modules and shared query hooks; add `features/clarifications/` public API/card/answer/assumption components. Extend requirements/run status/table, documents/version viewer, chat/header and workspace navigation. Honor import contracts through feature public APIs/shared API.

**Interfaces:** One `ClarificationCard` reads `question_id`/revision and submits the same persisted command from requirements and chat; query keys include task/run/history. `DiscussionSubject` renders source revision/backlink. Requirement deep link restores run and selected ID; source deep link restores immutable version/fragment and optional explicit run context.

- [ ] Add Vitest/component tests for pending operation recovery with exact original payload, stale revision retaining draft, two blockers with first effective update, scope selection, question-free requirement discussion, shared card invalidation, source-only vs explicit analysis discussion. Observe RED.
- [ ] Implement waiting status/blocking count, question basis/dependent decision/source, answer provenance and assumption risk navigation/status actions. Add fresh-history option to analysis form. Distinguish successful persisted answer from free chat text. Keep query retries for mutations off.
- [ ] Run pnpm lint/typecheck/test/build and fast gate; commit.

## Task 6: Acceptance inputs, browser tests and real model evidence

**Files:** Add `docs/examples/pr3/reporting-system-{complete,incomplete}.md`, `frontend/e2e/clarifications.spec.ts`, `backend/tests/unit/test_pr3_inputs.py`, `tools/clarification_smoke.py`, `docs/technical/pr3-verification.md`; extend quality runtime checks as needed. Update `CHANGELOG.md` under Unreleased.

- [ ] Input test proves full file equals cleaned subject parts I/II; incomplete differs only by deletion of the final R-04 sentence, retaining R-03/empty summary/all mandatory rules. Create files, preserve original PDFs/example.
- [ ] Playwright covers A–Г with controlled fake, real persistence and browser reopen/restart backend/postgres retaining volumes, plus nonblocking/cancel/post-resume error. Include the two-blocker and fragment/two-history paths in runtime acceptance.
- [ ] Run `uv run --locked --project backend python -m tools.quality full` from repository root and retain logs. Fix failures without bypassing hooks. Expected: all configured gates, integration tests, browser tests and runtime smoke pass.
- [ ] Run both input files on the available real local model, separate histories and one selected version each. Record endpoint/model/server/quantization/profile and actual questions/references, missed conditions/false blockers and whether the model distinguished the inputs. If unavailable, record concrete connection/error, exact reproduction command and unverified status. Fake and actual model results remain separate.
- [ ] Commit code/docs only after applicable gates pass.

## Task 7: Independent review and pull request

- [ ] Dispatch one fresh independent reviewer in a separate worktree against base `5610e66` and final head, with spec, plan and four added conditions. Resolve important findings with regression tests; run affected checks and full when justified by changes.
- [ ] Ensure clean branch, verified commits, no published bypass of failed hooks. Push this branch and open a separate PR to main; do not merge.
- [ ] PR description: direct branch links to both acceptance files; start commands and browser A–Г with expected outcomes; PostgreSQL race/recovery and four additional conditions; fake/CI vs actual local-model results; AC-01/AC-10 coverage only for proven scenarios; AC-18 partial. Return PR URL and remaining material limitations.

## Execution record — 27 November 2026

Tasks 1–6 are implemented. The first complete quality run passed, including 161
PostgreSQL tests, 23 browser tests and runtime failure/restart smoke. Final focused
regressions add 31 passing checks for source fingerprints, agent context, history
and ResumeRun; the pre-push full gate also discovers these tests. Two independent
reviews completed with no remaining Important/Critical findings after corrections.
See [verification evidence and actual model results](../../technical/pr3-verification.md).

The actual local model failed extraction language validation for both acceptance
inputs before clarification; semantic clarification quality remains unevaluated.
Publication is a separate PR to main for the user's review; merge is reserved to
the user. The checkbox tasks above retain the original execution checklist.

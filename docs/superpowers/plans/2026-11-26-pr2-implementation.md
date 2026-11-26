# PR 2 Implementation Plan

> **For agentic workers:** use superpowers:executing-plans and isolated parallel worktrees.
> User requested continuous implementation; approval is needed only for substantial new decisions.

**Goal:** document upload → immutable version → parsing → complete context → structured
generation → verified provenance → persisted candidates → A-01 and exact source viewer.

**Architecture:** existing Domain/Application/adapter/DI boundaries; PostgreSQL and local
immutable files; generic LangChain generator; minimal LangGraph with PostgreSQL checkpoints.

**Tech Stack:** Python 3.13, uv, FastAPI, Dishka, SQLAlchemy, Alembic, LangChain,
LangGraph, Pydantic, React, pnpm 12, TanStack Query, existing quality runner.

## Tasks

1. Source feature (`domain/documents.py`, application document modules, persistence and
   migration 0004, local files/parser adapters, document HTTP routes). Test immutable old
   versions, operation replay/conflict, concurrent upload, traversal/MIME/size, corrupt or
   missing originals, scope, stable parsed locators and recovery before implementation.
2. Generic structured generation (`application/structured*`, infrastructure adapter).
   Test explicit native schema/JSON text, strict validation, correction, shared request
   budget, deadline, rate limits, cancellation, empty/truncated/refusal and SDK retries=0.
3. Context and agent (`application/extraction*`, `domain/requirements.py`). ContextBuilder
   accounts for prompt/schema/output/reserve and partitions all immutable fragments;
   oversized input fails explicitly. Test coverage, injection boundaries, invented IDs,
   false quotes, context membership and typed requirement/gap/contradiction candidates.
4. Persistence and orchestration (migration 0005, extraction store/service/worker,
   `infrastructure/extraction_graph.py`, DI). Test command replay, preserved history,
   cancellation races, restart/checkpoint recovery, repeated nodes and request reservations.
   SQL holds no LLM waits; graph stores references to durable part results.
5. Frontend documents/A-01: independent features with shared API contracts. Test uploads,
   explicit revisions, source navigation, filters, progress/error/cancel/history and themes.
6. Integrate fake structured endpoint, Compose/env/README and synthetic fixtures. Run
   real PostgreSQL integration and Playwright through isolated quality runtime; preserve chat.
7. Measure real local model capabilities and BRD extraction separately from fake CI.
   Record parameters, precision/recall/F1, citations, coverage, validation, retries and time.
8. Update Unreleased, run `uv run --locked --project backend python -m tools.quality full`,
   independently review diff, fix verified findings, commit increments and open one PR.
   Monitor CI; never merge automatically.

Each implementation step: failing focused test → implementation → passing checks → commit
after existing hooks. Full checks run after integration. Baseline: 50 unit tests passed.

## Review focus

Interrupted publication, stale parse integrity, foreign scope/version, quotes from omitted
context, long table rows, persisted request budget across restart and cancellation at commit.

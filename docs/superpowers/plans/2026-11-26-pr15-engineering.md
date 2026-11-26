# PR 15 engineering follow-up

Scope: the additional review supplied on 26 November, in the existing
`feat/pr1-working-chat` branch. No merge, new PR, downloaded weights or new
application infrastructure.

1. Restore usable real-model chat: load the existing local Qwen model in
   LM Studio, persist the ignored local profile, verify streaming/cancel/history
   through the app, and leave the real profile running.
2. Review/refactor backend responsibilities: separate DTO/errors, prefer query
   composition, keep transactional command checks atomic, retain only justified
   application orchestration and the minimal resource-safe LLM port. Type all
   handwritten source assignments/functions; type semantic status/error values.
3. Type baseline backend tests and tools without `Any`/blanket ignores; include
   them in Ruff, Mypy strict, Pylint, Bandit and WPS231 with narrow test rules.
   Review available annotation rules instead of building a complex custom linter.
4. Use one cross-platform quality runner from pre-commit, pre-push and CI.
   Commit hooks run static/architecture checks and fast unit tests; push runs
   full checks, audits, isolated PostgreSQL/fake Compose, E2E and restart smoke.
   Test actual Git rejection with deliberate violations in an isolated checkout.
5. Review context budgeting and streaming costs. Keep whole conversation turns,
   account for system/template overhead and output reserve; use bounded chunk
   batching only if tests preserve latency, cancellation and partial durability.
6. Narrow PDF triggers to publication inputs, avoid duplicate application runs,
   preserve mandatory PR/main checks and manual PDF execution. Add Unreleased
   CHANGELOG; update AGENTS/quality docs briefly. Verify local hooks, real model
   smoke and CI on the final pushed commit.

Decisions: reuse existing tools and pinned runtimes. Keep fake LLM in ordinary
quality checks. Use separate test project/ports/volumes so checks never restart
or replace the developer's real-model application. Python loop/with/unpacking
targets are declared in their containing scope where inline annotations are
not valid syntax. Constants use Final; Enum members retain valid Enum syntax.

Execution:

- Baseline: source branch is clean at a4e092d; LM Studio API runs on 1234 but
  had no loaded model; the app was configured for fake-chat.
- Local ignored .env now selects existing Qwen2.5 Coder 14B, context 4096.

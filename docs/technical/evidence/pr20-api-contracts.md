# PR 20: generated HTTP contracts

The core patch adds the shared offline FastAPI route factory, OpenAPI export,
pinned `@hey-api/openapi-ts` 0.99.0, TypeScript/Zod 4 generation, generated network
schemas at the existing adapters, and the CI drift check. pnpm 12.21.0 and Node
26.13.1 were verified locally; the existing pnpm store was reused without changing
global settings or caches.

The transport, SSE framing/reconciliation, drafts, storage and replay flows remain
in their existing modules. Generated schemas replace handwritten network shapes.
Test fixtures use valid UUIDs, distinct valid checksum strings, ISO dates, and the
complete emitted DTO fields. Input defaults remain optional; output DTO schemas
describe the defaults that FastAPI actually emits.

## Evidence

- The offline export regression first failed because the exporter was absent.
  It then caught missing required output-default fields. The final offline test
  passes with database and HTTP-client construction blocked and exports identical
  bytes on two runs.
- The response-boundary regressions against the original handwritten client gave
  **2 failed, 1 passed**. Restoring the generated schemas gave **3 passed**.
  They cover invalid UUID/date responses, timezone offsets, enums, unions,
  optional request fields and nullable values.
- Adding `conflict_assessment_prompt_version` to the actual backend DTOs made
  `api:check` exit 1 and identify the stale OpenAPI, TypeScript and Zod files.
  Regeneration followed by fresh generation/check passed. No timestamp or
  temporary-directory value appears in the generated artifacts.
- Full Vitest: **107 passed, 0 skipped**. Coverage: statements **93.35%**,
  branches **85.89%**, functions **91.97%**, lines **94.83%**.
- TypeScript, ESLint, Prettier, production build, Mypy (267 files), focused Pylint
  (10.00/10), Bandit and WPS231 passed. The build retains the existing warning
  for a bundle larger than 500 kB. Generated types have one targeted ESLint
  exception for a faithfully generated enum-or-string union; handwritten code
  retains the rule.

No Playwright or real-model semantic acceptance was performed in this scope.
The parent integrates the shared factory into `di.main` and regenerates after
the concurrent clarification-assessment/error-model changes. Those final root
artifacts and their end-to-end checks are outside this isolated snapshot.

## Reproduction

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend api:generate
pnpm --dir frontend api:check
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend format:check
pnpm --dir frontend test
pnpm --dir frontend build
uv run --locked --project backend python -m pytest backend/tests/unit/test_openapi_export.py -q
```

The generator's [Zod 4 documentation](https://heyapi.dev/docs/openapi/typescript/plugins/zod)
documents generation of request/response definitions and timezone-offset support.

# Instructions for Codex agents

## Repository state and scope

- PR 1 supplies the backend, React frontend, local Compose runtime, and chat tests alongside the specifications. Frontend dependencies require `frontend/package.json`.
- Follow [frontend architecture](docs/technical/frontend.md) and [quality/testing plan](docs/technical/quality-and-testing.md). Applicable PR 1 checks are configured in `.github/workflows/quality.yml`; later-stage checks remain planned. Run the checks before claiming they pass.
- Do not merge a task branch or an AI proposal without the user's authorization.

## Frontend package manager

- **Use pnpm 12 for the frontend.** When creating `frontend/package.json`, set its `packageManager` to the **exact verified pnpm version**, commit `frontend/pnpm-lock.yaml`, and use pnpm consistently. Do not create `package-lock.json` or run `npm install` for the frontend.
- Use `pnpm install --frozen-lockfile` in CI; once the frontend exists, provide reproducible `lint`, `typecheck`, `test`, and `build` scripts. On Windows PowerShell, `pnpm.cmd` avoids PowerShell script execution-policy issues.
- The developer has Node.js 26.13.1 and pnpm 12.21.0 installed (19 November 2026). This is **not** proof that all selected frontend dependencies pass integration checks; choose/pin the CI Node major after the first actual frontend smoke. The original library evaluation planned Node 24 LTS.
- Backend Python dependencies are managed with **uv**, independently of the frontend.

## Multiple agents, worktrees, and disk space

- When agents work concurrently, give each a separate Git worktree/branch; never share or edit one worktree's `node_modules` from another. A conventional checkout plus sibling worktrees is sufficient; a bare Git clone is not required.
- pnpm can reuse a package store across worktrees. Efficient hard-link deduplication requires the store and the worktrees to be on the same filesystem. By default pnpm can choose a per-drive store; `pnpm store path` run from `C:\Windows\system32` is not evidence of the store path used by a project on D:.
- **Never move, delete, clean, or reconfigure the developer's global pnpm store/caches without explicit authorization.** Do not hardcode local absolute paths in repository configuration.

## Quality gates

- Use type-aware ESLint, architectural import contracts, cycle checks, complexity/depth limits, React Refresh validation, Prettier, strict TypeScript, Vitest, and the planned Playwright coverage as documented.
- Add actionlint, yamllint, markdownlint-cli2, and carefully configured typos checks as part of repository CI implementation, without removing the existing PDF workflow. No real paid LLM API calls are required in ordinary PR CI.
- Use `uv run --locked --project backend python -m tools.quality setup` to install local hooks. `fast` is the pre-commit gate; `full` is the pre-push and CI gate. See the quality plan for scope and prerequisites; do not bypass failed hooks to publish changes.
- Add explicit types to handwritten backend source, migrations, tests and `tools/`: parameters, returns, assignment targets, attributes and constants (`Final` where appropriate). Keep `Any` and unvalidated boundary values out of application code. Respect syntax limits for Enum members, comprehensions and pattern bindings; use existing Ruff/Mypy gates and review local annotation coverage.
- Update the root `CHANGELOG.md` under Unreleased for significant user-facing or technical changes. Do not invent a release version before a release.

## Backend naming and structure

- Prefer names that explain the object or action without surrounding context:
  `files_storage`, `document_parser`, `staged_file`, `requirements_extraction_agent`.
  Avoid generic dependency names such as `files`, `parser`, `agent` or `parts`
  when the domain meaning is otherwise unclear.
- Name classes and modules after their responsibility (`DocumentService`,
  `ExtractionContextBuilder`, `StructuredOutputGenerator`). Use verb-and-object
  method names such as `get_parsed_document`, `get_upload_operation`,
  `recover_uploads` and `attach_document`.
- Name interface modules `*_protocols.py`, rather than `*_ports.py`. Group related
  models, errors, prompts, protocols, agents, validation and workflow phases into
  focused packages as the layer grows. Avoid packages containing only a trivial file.
- Keep use-case orchestration in application services and database access in
  persistence stores. A service coordinating storage and parsing is not a repository.
- Prefer domain enums and typed dataclasses/DTOs over repeated string literals and
  unstructured dictionaries. Keep framework-required mappings at adapter boundaries.
- Retain explicit local annotations, including obvious assignment types; the user
  confirmed this preference during the PR 2 review. Annotate asynchronous generators
  with `AsyncGenerator`, and iterator inputs/contracts with `AsyncIterator` as appropriate.

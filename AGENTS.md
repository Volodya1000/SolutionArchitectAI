# Instructions for Codex agents

## Repository state and scope

- SolutionArchitectAI currently contains specifications and documentation; the React frontend has not yet been scaffolded. Do not install frontend dependencies until its `package.json` exists.
- Follow [frontend architecture](docs/technical/frontend.md) and [quality/testing plan](docs/technical/quality-and-testing.md). The checks described there are planned, not already passing.
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

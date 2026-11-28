# PR 20 focused protocol and mandatory-conflict browser regression

Root-compatible changes were authored from read-only snapshots of the current parent files. No root files were edited by this agent.

## Protocol gate

The original parent protocol reproduced Pylint R0904: 22 public methods, limit 20. The replacement separates read (4), command (5), execution (8) and review (5) contracts. ClarificationStore inherits those focused Protocols. All 22 method declarations match the original AST exactly, including the parent's typed operation result; callers and HTTP contracts stay compatible. No gate configuration or suppression changed.

`uv run --locked --project backend python -m pylint --rcfile backend/pyproject.toml .build/root-controls-after/clarification_protocols.py tools/fake_llm/server.py backend/tests/unit/test_fake_mandatory_conflict.py`: **10.00/10**, all checks passed. Mypy on those three source files: **passed**. Configured Ruff and cognitive checks: **passed**.

## Controlled fake model

Only tools/fake_llm/server.py recognizes [clarification:mandatory-conflict]. The controlled extraction emits one contradiction with two authentic selected source statements; clarification returns questions:[]; the independent assessment confirms with both exact statements. Production application code and prompts contain no fixture marker. The parent's discussion_citation short-reference function matches its original AST exactly.

Regression-first unit command `uv run --locked --project backend python -m pytest backend/tests/unit/test_fake_mandatory_conflict.py -q`: before change **2 failed**, after change **2 passed**, **2 collected**, **0 skipped**. Typed production schema validation checks the controlled responses and exact original statements.

## Browser flow

New frontend/e2e/mandatory-conflict.spec.ts uses visible upload and A-01/A-07 actions: independently confirmed two-source blocker; assume; risk open; confirm through A-01; analysis still waits with the conflict reason and factual-answer action; closed risk retains confirmation reason; factual answer on revision 2; automatic continuation completes the same run; old confirmed assumption, new factual decision and single closed risk remain visible and no new model requests occur.

Own frontend dependencies were installed offline with verified pnpm 12.21.0, frozen lockfile, all 655 packages reused and zero downloads. Own worktree node_modules was used; parent's node_modules was not shared. No package manifest or lockfile changed. Prettier 3.10.1 parses, formats and checks the new Playwright source successfully.

Full browser runtime execution and integrated frontend type/lint gates are parent-owned as explicitly requested; this report does not claim a Playwright runtime pass.

Patch files: root-protocol-composition.patch, root-mandatory-fake.patch, mandatory-conflict-e2e.patch. Each passed git apply --check against the observed parent state. No commits, pushes, merges, demo volume changes or paid model calls.

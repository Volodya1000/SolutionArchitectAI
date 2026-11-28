# PR20 test quality verification

Baseline: `75ad38f19138632dd78485faad436f44b385a3db`, verified against the open
PR #20 head on 28 November 2026. Work continues in `codex/pr3-clarifications`;
merge belongs to Volodya. This report concerns the approved testing-quality task.
The earlier real-model acceptance remains a separate open criterion in the
[acceptance checklist](pr20-acceptance-fixes.md).

## Baseline and method

Reviewed all 24 Markdown files (README and 23 notes) at notes commit
`de613d951f73f017f92f93509957b3e82d6ca0e1`, current tests/configuration and PR3
acceptance evidence. Interpret the notes through observable behavior and the
project's real concurrency contracts, without mechanical assertion/mock/loop bans.

The baseline full gate passed: 409 fast Python scenarios, 42 quality probes,
305 PostgreSQL/SDK scenarios, 121 Vitest scenarios and 35 Playwright scenarios.
The quality probes overlap the old fast selection and are not additive.
Backend combined line/branch coverage was 94.42%; frontend raw coverage was
94.29% lines and 86.02% branches. Baseline full wall time: 838.71 seconds.

## Confirmed findings and changes

- Requirement payload expectations were vacuous for missing records and used
  identical source/normalized text. They now check exact cardinality, unique IDs,
  the full ID-to-data mapping and both input permutations with distinct wording.
- Message roles used the enum itself as an oracle. Backend and frontend now pin
  the literal external strings independently; generated-contract drift remains gated.
- The discussion validation test repaired route registration and omitted every
  field. It now uses `create_app()` and checks only missing/invalid `subject` with
  a valid operation ID and the exact validation location/type. Four additional
  HTTP suites now use the production route assembler instead of including routers;
  input/scope/pagination/forged-author checks identify their actual failing fields.
- The SSE heartbeat test stopped before it could detect early exhaustion. It now
  observes unchanged state, a second heartbeat, a newer terminal frame and exhaustion
  with deterministic scheduling. Canonical path comparison tests use value equality.
- Five ORM session mocks became real PostgreSQL corruption/input tests. Pure JSON,
  status conversion and availability/error mapping remain fast. Durable assertions
  use separate sessions and verify rollback/budget preservation.
- Each PostgreSQL case gets a database cloned from the migrated dedicated test
  template. Recovery uses the real dispatcher; pending tests assert the exact set.
  Graph restart assertions now protect stable IDs, completion, persisted uniqueness
  and no repeated completed generation instead of private checkpoint shape/nodes.
- Both real SDK clients have controlled transports and ignore ambient proxies.
  The 43 HTTP-adapter scenarios run once in fast/full; full excludes their second
  execution. Already-run fast quality probes are also deselected in full.
- Frontend equal-sequence, HTTP/SSE race and panel/draft tests assert public behavior.
  The additional result-refresh test now receives status through HTTP rather than
  setting a query-cache key. Matching MSW responses are explicit server outcomes;
  backend matching/history algorithms remain tested on PostgreSQL. Test helpers
  are excluded from production coverage.
- Eleven initial Testing Library node-access warnings were reviewed and removed;
  the rule is now blocking. Actual side-by-side layout is checked in Playwright.
  An accessible answer-form name also supports stale form-submission verification.

## Automatic prevention

Import-linter adds a product-to-pytest/test-helpers prohibition while retaining all
existing boundaries. Ruff retains PT/PT012 and additionally checks test/helper
private access. A small typed AST rule blocks SQLAlchemy session mock specs,
including imported aliases, positional specs, qualified names and instances; no
session-mock exceptions remain. It deliberately does not perform dynamic data flow.

ESLint adds scoped Vitest, Testing Library and Playwright rules and forbids product
imports of frontend test infrastructure. The pinned plugins are 1.6.28, 7.16.3 and
2.12.2 respectively; their peer ranges and rejection probes were checked against
ESLint 9.39.5, TypeScript 6.0.3 and Vitest 5.1.1. Playwright's optional page/locator
await checks are enabled explicitly. No coverage floors were changed.

## Targeted experiments

Exact replacements and commands are retained in the
[mutation evidence](evidence/pr20-test-quality-mutations-2026-11-28.json). Every
temporary defect is restored; these experiments are not a global mutation score.

| Mutation | Old targeted tests | Improved targeted tests |
| --- | --- | --- |
| Send only the first requirement | Survived | Detected |
| Send no requirements | Survived | Detected |
| Replace original text with normalized text | Survived | Detected |
| Duplicate the first requirement instead of the second | Survived | Detected |
| Associate all data with the last requirement ID | Detected | Detected |
| Serialize assistant as bot | Survived | Detected |
| Remove production discussion-route registration | Survived | Detected |
| Make subject optional | Survived | Detected |
| End SSE after the first heartbeat | Survived | Detected |
| Accept equal sequence by changing <= to < | Survived | Detected |
| Return a new equal canonical path (harmless) | False failure | Passed |

Adding an unused `checkpoint_extension` field to `GraphState` caused the original
restart test to fail on its exact key-set assertion; the improved PostgreSQL restart
test passed (2.27 seconds). A transparent DOM wrapper around `DiscussionHeader`
preserved all three semantic panel/draft tests. Both changes were restored.

Independent review found one additional gap: explicit matching responses no longer
observed outgoing request parameters. Added three independent request-contract
cases (selected version IDs, trimmed scope, history mode/ID) and awaited the changed
scope in the UI scenario. An empty-scope mutation failed all three contract cases;
after restoration all 24 targeted matching/document/refresh cases passed.

The original SDK suite failed 41/43 cases with `ALL_PROXY=socks://127.0.0.1:9`;
the changed suite passed 43/43 with that value and with a separate combination of
unreachable HTTP/SOCKS5 proxy variables. The initial SOCKS5 baseline experiment
hit its 60-second harness timeout and was discarded; all files were restored in
`finally`. The invalid-scheme baseline above provides the controlled comparison.

The PostgreSQL suite passed 267 scenarios with reversed file order in 251.35 seconds
before the two explicit isolation-invariant cases were added. The first attempt
to reverse individual node IDs exceeded Windows' command-line limit; it did not
execute tests. Reversing file paths resolved that harness limit. Normal final full
execution also includes the two committed-state isolation cases.

Ruff/Mypy/Pylint and frontend contract probes found no remaining issues in their
latest targeted runs. Final gate results below remain authoritative.

## Verification results

### Collection before and after

The requested `269626a` audit is superseded by a fresh collection at `75ad38f`.
Python definitions are AST function definitions named `test_*`; scenarios come
from pytest collection. Frontend definitions are TypeScript AST `it`/`test` calls,
including a parameterized definition once; scenarios come from the test runners.

| Suite | Files before / after | Definitions before / after | Scenarios before / after |
| --- | --- | --- | --- |
| Backend unit | 48 / 49 | 215 / 211 | 398 / 397 |
| Backend integration, including SDK | 31 / 33 | 184 / 190 | 305 / 312 |
| Backend quality | 5 / 6 | 22 / 26 | 42 / 64 |
| Frontend Vitest | 20 / 22 | 104 / 107 | 121 / 129 |
| Frontend Playwright | 9 / 9 | 29 / 29 | 35 / 35 |

New Python collection: 773 unique scenarios. Fast selects 397 unit, 43 SDK and
24 quality scenarios; full adds 40 remaining quality and 269 PostgreSQL scenarios.
The two integration/SDK categories describe dependency level and disk location,
not an instruction to run an SDK scenario twice. More scenarios are not a quality
verdict; the targeted mutations above provide the relevant evidence.

### Comparable coverage and timings

Baseline fast was rerun in a separate worktree with its own dependencies: 248.84
seconds, 409 Python and 121 Vitest passed. Baseline full: 838.71 seconds. The
baseline frontend reporter additionally emitted per-file JSON; summing the same
production files after excluding the two test-support modules gives these values:

| Metric | Baseline with comparable exclusions | Final |
| --- | --- | --- |
| Frontend lines | 1046/1111 = 94.14% | 1046/1111 = 94.14% |
| Frontend branches | 827/961 = 86.05% | 827/961 = 86.05% |
| Frontend statements | 1127/1217 = 92.60% | 1127/1217 = 92.60% |
| Frontend functions | 355/392 = 90.56% | 355/392 = 90.56% |
| Backend combined lines/branches | 94.42% | 94.41% |
| Fast wall time | 248.84 s | 184.71 s |
| Full wall time | 838.71 s | 851.39 s |

The old raw frontend 94.29%/86.02% used a different denominator including test
support. Its apparent change cannot be interpreted as a production coverage loss.
Gate wall times include static tools, Docker/build/start/restart costs and host
contention; they are observations, not statistically controlled performance claims.

### Checks and dependency levels

- **Controlled HTTP/domain:** complete 397-unit suite, 43 real-SDK transport
  scenarios, 64 quality probes (24 fast + 40 remaining) and 129 Vitest scenarios passed.
- **PostgreSQL:** full normal-order 269 scenarios passed, including the five moved
  cases and two isolation invariants. The earlier reversed-order 267-case run is
  recorded separately above. Real transactions/locks/commit/recovery were retained.
- **Browser/fake model:** all 35 Playwright scenarios passed, including actual
  source-panel/composer geometry. Runtime smoke passed for SSE disconnect,
  cancellation, graceful/abrupt restart, PostgreSQL restart/outage and history isolation.
- **Static/build:** Ruff (including PT012 and scoped SLF001), formatting, strict
  Mypy, Pylint, Bandit, all five import contracts, complexity, ESLint, TypeScript,
  frontend rejection probes, production build, YAML/Markdown/actionlint/typos,
  local links, OpenAPI drift and both dependency audits passed.
- **Hooks:** backend commit passed the installed pre-commit hook. Its first attempt
  correctly failed WPS231 in the new AST importer; the function was simplified and
  the existing threshold was retained. Final commits and publication run the same
  mandatory fast/pre-push full hooks; no hook is bypassed.
- **Actions:** the final published SHA and live Actions result are maintained in
  [PR #20](https://github.com/Volodya1000/SolutionArchitectAI/pull/20). The existing
  PDF workflow is unchanged. Repository text cannot record its own future commit SHA.
- **Real models:** no new paid or local real-model requests were made for this
  testing-quality task; previous Qwen evidence remains failed and is not reclassified.

The timing run precedes final assertion-only cleanup; mandatory publication hooks
and Actions recheck the final tree. An additional history-recovery test now uses a
controlled response gate instead of a 1400 ms delay, asserting that repeated SSE
failures do not restart an in-flight HTTP read. Changing `cancelRefetch` to true
failed the test; restoration passed. Source quote/link association is preserved
through semantic article queries, without requiring DOM ancestry or source-card order.

### Limits

No global lint exemptions or lowered coverage floors were introduced. The
PostgreSQL role needs CREATEDB and the migrated test template must be unused by
application sessions. Parallel CI execution has not been enabled or claimed.

The AST guard intentionally resolves imports, not general dynamic aliases or
lexical data flow. Reusing one alias for different imports in distinct local scopes
can overwrite its simple name map. No such unresolved case remains in this suite;
this tool does not replace review of arbitrary dynamic Python. There are no new
global lint exemptions or lowered coverage thresholds.

The original SQLSTATE/mandatory-conflict/real-Qwen acceptance evidence keeps its
original scope. This testing-quality iteration neither changes model prompts or
profiles nor turns the previously failed live Qwen scenario into an accepted one.

A temporary baseline checkout was deregistered after benchmarking. Automatic
approval review denied recursive cleanup of its residual directory; global pnpm
store/cache configuration and contents were not moved or cleaned.

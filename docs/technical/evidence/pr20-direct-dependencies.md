# PR 20 directly injected workflow dependencies

Apply after continuation-failure.patch.

ClarificationWorkflow now receives its extraction store, context assembler, shared budget builder, immutable policy, clarification agent and document service directly through Dishka. It no longer reaches through ExtractionSteps into a part extractor. ExtractionSteps is a thin dataclass coordinating injected assembler, extractor and finalizer; its synchronizing policy setter is removed. ExtractionBudgetBuilder owns persistent request reservations and budget construction shared by extraction and clarification.

Dishka class providers assemble the dataclass services. Budget/profile tests construct a separate limited collaborator graph, without mutating the application's shared policy. Checkpoint restoration tests patch the directly injected document service.

Verification:

- `uv run --locked --project backend python -m pytest backend/tests/integration/test_extraction_lifecycle.py backend/tests/integration/test_clarification_cycle_recovery.py backend/tests/integration/test_clarification_http.py backend/tests/integration/test_pr20_durable_review.py -q`: **37 passed**, **37 collected**, no skips, before adding the final assessment-cache parameter.
- Initial same targeted run: **34 passed, 1 failed** because a model-profile test still monkeypatched the removed policy setter. It now supplies a separate configured steps object to the graph, preserving the tested mismatch behavior.
- `... python -m mypy --config-file backend/pyproject.toml backend/src backend/tests backend/test_helpers tools`: **277 source files passed**.
- Configured Ruff: **passed**. Formatter: **280 files already formatted**.
- Changed workflows/provider/helpers/durable tests Pylint: **10.00/10**.

Additional durable replay cases verify failed model output creates no cached step, failed request reservations remain in cumulative review metadata after recovery, a cached foreign requirement is rejected before generation, and a foreign task cannot read saved steps. The final cache parameter also replays independent conflict assessments without issuing duplicate calls.

All PostgreSQL tests use only own isolated *_test databases. No commits, pushes, merges, global package-store changes, demo volume changes or paid model requests.

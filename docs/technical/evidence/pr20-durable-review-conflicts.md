# PR 20 durable clarification review and conflict assessment

Apply after `clarification-lifecycle.patch` and `history-window-splitting.patch`, based on `269626a7d3b88293624a419e3ff56983429b9d66`.

## Corrected conflict provenance

Extraction category CONTRADICTION and a VERIFIED source quote are hypotheses and citation integrity, respectively. Neither alone establishes a mandatory corporate rule conflict. A separate bounded assessment now returns candidate, confirmed or refuted with reason and authentic exact-source evidence; confirmation requires two distinct source statements. Refutation requires a resolving cited condition. Conflicting assessments remain candidate. Existing saved mandatory_conflict questions keep their established audit when candidate wording narrows within the same pinned source.

`ClarificationView.conflict_assessments` defaults to an empty list for older saved results; each item contains requirement_id, status, reason and sources (unchanged SourceRef). Only confirmed assessments create mandatory blocking questions. Unverified or refuted candidates remain visible diagnostics. Persisted confirmed assessments are enforced by question-save fallback, explicit resume and completion even if the question model returns valid questions:[].

Prompt version: `conflict-assessment-1` from application/prompts/conflict_assessment_prompt.py. Metadata records conflict_assessment_prompt_version. Parent's pipeline-version/fingerprint change imports the same constant separately.

## Durable review steps

Migration 0008_review_steps adds a per-run validated step result cache. Migration 0009_conflict_assessments adds a compatible []-default run assessment field. Cache keys include fully rendered prompt/schema, model profile, immutable source identities/content/offsets, real requirement bindings, relevant history and decision revisions, and assessment subject. Successful question windows retain IDs; successful source verdicts and conflict assessments also replay. Failed or invalid model output is never saved. Read and write transactions are short and close before model requests.

Authoritative request reservations persist before model invocation. Metadata review_start_requests retains the original review baseline across restart, including failed requests; replay does not reserve requests again. Coverage is reconstructed by consuming validated saved windows and reports completion only after source/history review finishes.

## Regression and verification evidence

- Before cache implementation, real PostgreSQL workflow crash after all validated questions/verdicts but before final atomic question save repeated all 16 model requests (32 observed), failing the no-repeat assertion.
- After cache implementation, same crash replays with no new requests. Crash after individual validated window commit but before progress metadata commit also replays that window. A fresh worker resumes the persisted LangGraph CLARIFY checkpoint and does not repeat completed source subwindows.
- Semantic regression before correction: `test_extraction_contradiction_hypothesis_can_be_refuted_by_authentic_source` failed because category-only mandatory assignment retained the false blocker.
- `uv run --locked --project backend python -m pytest backend/tests/integration/test_pr20_known_conflict.py backend/tests/integration/test_pr20_conflict_recovery.py backend/tests/integration/test_pr20_durable_review.py backend/tests/unit/test_pr20_bounded_review.py -q`: **24 passed**, **24 collected**, no skips, before adding the unverified diagnostic case.
- After adding that case, `... python -m pytest backend/tests/integration/test_pr20_conflict_recovery.py -q`: **6 passed**, **6 collected**, no skips.
- Worker false-conflict coverage includes functional false question, false CONTRADICTION with a question, and false CONTRADICTION with valid empty questions; authentic resolving source permits completion and assessment remains refuted.
- `... python -m mypy --config-file backend/pyproject.toml backend/src backend/tests backend/test_helpers tools`: **274 source files passed**.
- Configured repository Ruff: **passed**. Configured formatter: **277 files already formatted**.
- Runtime remains only isolated Compose project saa-quality-clarification-lifecycle and solution_architect_test database. No demo volume changes or paid model requests. Model stubs prove workflow/state behavior, not semantic model quality.

Full integrated repository verification remains parent-owned; later dependency injection changes are a separate increment.

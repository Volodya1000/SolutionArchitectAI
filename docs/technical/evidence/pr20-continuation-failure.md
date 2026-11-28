# PR 20 completed-continuation recovery

Apply after durable-review-conflicts.patch. No additional schema change.

A failed continuation of a previously completed run previously retained resume_pending because terminal ExtractionView transitions preserve COMPLETED. Scheduler repeatedly selected the poisoned old continuation and never dispatched its queued neighbor at concurrency one.

Regression: real isolated PostgreSQL/fake worker scheduler, seeded COMPLETED plus resume_pending plus missing source before a valid queued neighbor. Before fix the neighbor timed out (**1 failed**, 11.78 seconds); after fix it completes while the original completed requirements and completed cycle remain unchanged.

Worker captures the durable resume version before resumed completed work. Terminal continuation failure stores the existing public ExtractionView.error_code and clears resume_pending only for that captured version. A concurrently queued newer resume remains pending. Successful completion clears error_code and preserves completed cycle audit. Failure is visible without rewriting the old completed result as a failed extraction.

Tests: `uv run --locked --project backend python -m pytest backend/tests/integration/test_pr20_continuation_failure.py backend/tests/integration/test_pr20_review_persistence_regressions.py -q`: **5 passed**, **5 collected**, no skips. Includes stale failure versus newer resume and successful retry diagnostic clearing. Uses only solution_architect_continuation_test in own saa-quality-clarification-lifecycle PostgreSQL container.

Also hardens cache source validation to reassemble split fragments through the existing history matcher, preserving exact immutable pin checks; candidate assessments retain original source references when no conclusive evidence is returned. Updates the legacy nonblocking conflict fixture to seed an explicitly established assessment, matching corrected provenance.

Broad semantic verification: clean-env nonintegration **382 passed, 202 deselected**; integration **229 passed, 1 failed** before that fixture update. Failure name: test_known_conflict_cannot_complete_with_legacy_nonblocking_flag; explicit marker fixture correction is included and its test passes above. Mypy all application/tests/helpers/tools: **275 source files passed**. No paid model calls or developer demo volume changes.

# PR 20 history-window source splitting

Base: `269626a7d3b88293624a419e3ff56983429b9d66`; apply after clarification lifecycle patch.

Regression: a source window fits alone and each half fits with one historical question, while the full window plus that question exceeds the measured model context. The original planner raised `context_too_large` immediately instead of splitting source and requirement context while preserving history.

Red: `uv run --locked --project backend pytest backend/tests/unit/test_pr20_history_window_splitting.py -q`: **1 failed, 1 passed** after correcting an initially oversized test question that exceeded the public 16000-character DTO limit. Expected failure was `history_windows` refusing the splittable source window.

Green: `uv run --locked --project backend python -m pytest backend/tests/unit/test_pr20_history_window_splitting.py backend/tests/unit/test_pr20_bounded_review.py -q`: **10 passed**, **10 collected**, no skips. Covers zero and two correction retries, actual rendered JSON-schema and correction-reservation token measurement, retained historical record in each output, exact source text coverage, bounded review coverage and indivisible historical record rejection.

Planner `source_windows` now optionally carries the same history through recursive source-fragment, requirement-list and source-text splits. Every final window is measured by `check_context`. `fits` imports parent's `CORRECTION_RESERVATION` to include diagnostic budget. The prompt constant was copied locally only for verification and is intentionally excluded from this patch; parent owns `structured_prompt.py`.

No database or API changes. Full combined verification and durable per-window replay are recorded separately.

# PR 20 review corrections

The user authorized updating the existing PR end to end, including eleven regressions,
UX improvements, backend refactoring and actual local-model acceptance. Base/head:
`d9ed00874a73c71067ddad7e2612d9ee7cf80a0f`; preserve the approved PR 3 guarantees.

## Decisions

- A changed applicable source/requirement invalidates inherited answers regardless of
  the optional model flag. Keep old/new basis and immutable decision origins. An unrelated
  paragraph edit retains the answer. Fingerprints establish applicability, not semantics.
- Typed context DTOs contain requirement wording, category and candidate evidence; JSON
  serialization occurs only at the model boundary. Separate prompts, schemas, validation,
  source fingerprints and history matching into focused modules.
- Clarification uses bounded source/requirement/history windows and an evidence-backed
  cross-window review before retaining a blocking gap. Count schema/service/output tokens;
  expose incomplete review explicitly. Never silently treat skipped evidence as absent.
- Known contradictions with mandatory rules remain blocking after an assumption. Ordinary
  assumptions still create one risk and allow continuation; no general rules engine.
- Reject unavailable history before queue insertion; contain legacy bad-job failures in
  that run. Waiting runs are selectable in UI matching but not executable while unanswered.
  Reading a legacy completed result preserves its original active duration.
- The discussion model and side panel consume the same server-selected scope. Add
  `GET /api/chats/{chat_id}/discussion/clarifications`, returning a scoped ClarificationView
  or null. Preserve candidate evidence verification separately from authentic source text.
- Requirements use three tabs (requirements/clarifications/risks), counts and an actionable
  waiting notice above the list. Discussion is a compact accessible row action. Full subject
  title appears in the side panel, with a concise generic chat heading. Decision metadata
  is a definition list/grid; technical IDs stay in disclosure. Drafts pin revision, sources
  and answer/assumption mode; stale text needs explicit transfer.
- Replace duplicated SQL factories with one infrastructure transaction scope using a PEP
  695 generic application Protocol, constructor composition and typed error translation.
  Keep store responsibilities distinct, five-second boundary, rollback and cancellation.
  Dishka supplies one sessionmaker and explicitly typed specializations.
- Name dependencies by responsibility across the PR. Keep semantic agent operations;
  the existing structured-model invoke boundary is already uniform, so no artificial base.

## Alternatives and limits

Hiding unwanted rows in the UI would leave invalid extracted candidates in storage; filter
structural Markdown before/at extraction validation while preserving original source bytes.
A single giant clarification prompt cannot satisfy bounded models; window and cross-review.
Five copied factories or one ORM-dependent application factory both retain architectural
problems; the shared application protocol stays ORM independent.

Inputs remain byte-identical. Actual-model failures are diagnosed without relaxing language
or citation checks or embedding the reporting example's answer in prompts. Evidence must
separate real inference from fake workflow tests. Existing PR only; no merge.

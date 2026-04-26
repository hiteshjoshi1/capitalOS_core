# Issue 156: Retrieval metadata weighting and ranking safety

## Objective
- Use document metadata already stored during ingestion to improve retrieval ranking quality, especially by down-weighting lower-authority corpus segments such as DJCO meeting notes relative to canonical talks and primary interviews.
- Keep the retrieval stack evidence-first and citation-safe while allowing ranking to respect corpus class, canonical status, and source quality.
- Ensure retrieval quality does not regress because of this change by requiring baseline comparison, guarded rollout behavior, and measurable verification.

## Architecture Decisions
- Decision 1: Metadata-aware weighting must be applied at retrieval/ranking time, not during ingestion. Ingestion remains responsible only for storing content and metadata.
- Decision 2: The first version should use already-available metadata fields such as `collection`, `canonical_status`, `dedupe_priority`, `work_type`, and optional numeric retrieval hints from `metadata_json`.
- Decision 3: Weighting must be generic and source-agnostic. It must not hardcode Charlie-specific, Buffett-specific, or source-URL-specific rules in code.
- Decision 4: Weight configuration should be driven by stable generic corpus classes, for example:
- Decision 4a: `canonical_talk`
- Decision 4b: `primary_interview`
- Decision 4c: `supplemental_qna`
- Decision 4d: `reference_material`
- Decision 5: The ranking layer may softly down-weight lower-authority document classes, but must never make valid evidence undiscoverable when it is the best available match.
- Decision 6: Weighting must be applied in a way that composes safely with the current retrieval stack:
- Decision 6a: dense similarity
- Decision 6b: sparse/keyword ranking
- Decision 6c: reciprocal rank fusion
- Decision 6d: optional reranking
- Decision 7: The first rollout must be conservative:
- Decision 7a: weighting should be mild by default
- Decision 7b: feature flag or config gate required
- Decision 7c: ability to compare weighted vs unweighted retrieval required
- Decision 8: Retrieval quality must be verified against the existing evaluation harness and representative corpus queries before weighting becomes default behavior.
- Decision 9: Missing metadata must fail safe. If a document lacks weighting metadata, retrieval should fall back to current ranking behavior instead of penalizing or excluding it.

## Acceptance Criteria
- [ ] Retrieval can read generic document metadata and apply optional ranking weights without requiring re-ingestion.
- [ ] Weighting logic is generic and does not hardcode author-specific or URL-specific corpus rules.
- [ ] The implementation supports at least these metadata inputs when present:
- [ ] `collection`
- [ ] `canonical_status`
- [ ] `work_type`
- [ ] `dedupe_priority`
- [ ] optional numeric retrieval hint in `metadata_json`
- [ ] The implementation defines a generic weighting strategy for corpus classes such as canonical talks, primary interviews, supplemental Q&A, and reference material.
- [ ] Lower-authority sources like DJCO can be down-weighted relative to canonical talks and primary interviews.
- [ ] Weighting is a soft ranking modifier, not a hard filter.
- [ ] Retrieval continues to return evidence with proper citations and metadata lineage.
- [ ] If weighting metadata is absent, retrieval behavior falls back safely to the current baseline behavior.
- [ ] A feature flag or equivalent rollout control exists so weighted retrieval can be enabled, disabled, and compared.
- [ ] A comparison path exists to inspect weighted vs unweighted retrieval results for the same query.
- [ ] Retrieval evaluation is run before and after the change using the existing evaluation harness or equivalent benchmark queries.
- [ ] The issue defines a concrete “no regression” bar, such as:
- [ ] no statistically meaningful drop on accepted benchmark metrics, or
- [ ] no material degradation on a fixed representative query set reviewed by a human
- [ ] Tests cover:
- [ ] metadata parsing and default behavior
- [ ] score adjustment behavior
- [ ] fallback behavior when metadata is missing
- [ ] weighted vs unweighted retrieval comparison path
- [ ] The implementation is verifiable via Makefile commands and curl-verifiable APIs where applicable.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not_started`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-26`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `<command or decision>`
- Open questions:
  - `Should weighted retrieval be applied before or after reciprocal rank fusion in the first version?`
  - `Should the first rollout use static config weights, DB-backed weights, or env-configured defaults?`
  - `Which representative evaluation queries must be treated as must-pass for the no-regression bar?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

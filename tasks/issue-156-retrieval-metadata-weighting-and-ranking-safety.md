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
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `completed`
- Workflow Status: `completed`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-27`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `make lint` passed after rerun in isolation; initial parallel run hit a transient Vitest temp-file race in ESLint.
- `typecheck`: `pass` — `make typecheck` passed (`tsc` clean; backend mypy skipped because not installed in api image).
- `tests`: `pass` — `make contract-backend`, `make test-backend`, `make contract-frontend`, `make test-frontend`, `make orch-test`, `make rag-eval-seed`, and `make rag-eval-compare CONFIG_A=hybrid+metadata_weighting_off CONFIG_B=hybrid+metadata_weighting_on`.
- `e2e`: `pass` — `make e2e`
- `api-smoke`: `pass` — `make api-smoke`
- `policy-checks`: `pass` — no-regression bar defined as `mean_ndcg@10 delta >= -0.02` and `mean_recall@10 delta >= -0.02`; `make rag-eval-compare ...` reported pass.

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `Makefile` — reason: fixed `rag-eval-seed` to point at the actual in-container fixture path (`/app/data/fixtures/rag_golden_queries.yaml`) so the evaluation harness is Makefile-verifiable.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Pipeline re-run / ship if review is satisfied.`
- Open questions:
- `Resolved in this implementation: weighting is retrieval-time only, env-gated, and applied as a soft modifier across dense/sparse ordering, RRF output ordering, and rerank tie-breaking.`
- `Resolved in this implementation: first rollout uses static env-configured defaults with request-level compare support; no re-ingestion required.`
- `Resolved in this implementation: no-regression bar is mean_ndcg@10 delta >= -0.02 and mean_recall@10 delta >= -0.02 on the existing eval harness compare output.`
- If PR raised but intent partial:
  - unmet criteria: `none`
  - follow-up issue: `none`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented generic, default-off retrieval metadata weighting with a weighted-vs-unweighted compare path, eval-harness support, and targeted tests; the required Makefile verification suite passed after rerunning lint in isolation to avoid a transient frontend temp-file race.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Retrieval reads stored generic document metadata at ranking time and can apply optional weighting without re-ingestion.
- Acceptance criterion: Weighting logic is generic and source-agnostic, with soft class-based adjustments for canonical talks, primary interviews, supplemental Q&A, and reference material.
- Acceptance criterion: Missing weighting metadata falls back safely to baseline behavior rather than filtering or penalizing evidence.
- Acceptance criterion: A feature flag and comparison path exist so weighted and unweighted retrieval can be enabled, disabled, and inspected side by side.
- Acceptance criterion: The existing eval harness can compare weighted vs unweighted retrieval and report a concrete no-regression bar.
- Acceptance criterion: Tests cover metadata parsing/defaults, score adjustment, fallback behavior, and the comparison path.
- Acceptance criterion: The change is verifiable through Makefile commands and curl-verifiable APIs.

## Prepare
Checked out `feature/issue-156-retrieval-metadata-weighting-and-ranking-safety` from `main` and ensured task file exists.

## Plan Summary
Keep ingestion unchanged, merge stored document metadata at retrieval time, apply mild generic corpus-class weights behind a feature flag, expose explicit weighted/unweighted comparison in API and eval flows, and verify with tests plus the full Makefile gate set.

### Architecture Decisions
- Apply metadata weighting only at retrieval/ranking time by merging already-stored document metadata into retrieved chunk metadata; no re-ingestion is required.
- Use generic corpus classes and metadata signals (`collection`, `canonical_status`, `work_type`, `dedupe_priority`, and optional retrieval hints) rather than author- or URL-specific rules.
- Keep rollout conservative and default-off via `RAG_RETRIEVAL_METADATA_WEIGHTING_ENABLED`, with explicit weighted vs unweighted compare paths in both API and eval flows.
- Define a concrete no-regression bar in eval compare output: weighted retrieval must not reduce `mean_ndcg@10` or `mean_recall@10` by more than 0.02.

### Acceptance Criteria
- Retrieval reads stored generic document metadata at ranking time and can apply optional weighting without re-ingestion.
- Weighting logic is generic and source-agnostic, with soft class-based adjustments for canonical talks, primary interviews, supplemental Q&A, and reference material.
- Missing weighting metadata falls back safely to baseline behavior rather than filtering or penalizing evidence.
- A feature flag and comparison path exist so weighted and unweighted retrieval can be enabled, disabled, and inspected side by side.
- The existing eval harness can compare weighted vs unweighted retrieval and report a concrete no-regression bar.
- Tests cover metadata parsing/defaults, score adjustment, fallback behavior, and the comparison path.
- The change is verifiable through Makefile commands and curl-verifiable APIs.

### Planned Paths
- `api/app/rag`
- `api/app/routers/rag.py`
- `api/tests`
- `tasks/issue-156-retrieval-metadata-weighting-and-ranking-safety.md`

## Build Summary
Implemented generic, default-off retrieval metadata weighting with a weighted-vs-unweighted compare path, eval-harness support, and targeted tests; the required Makefile verification suite passed after rerunning lint in isolation to avoid a transient frontend temp-file race.

### Changed Files
- `Makefile`
- `api/app/rag/concept_mode.py`
- `api/app/rag/eval/cli.py`
- `api/app/rag/eval/runner.py`
- `api/app/rag/retrieval.py`
- `api/app/rag/retrieval_weighting.py`
- `api/app/routers/rag.py`
- `api/tests/test_rag.py`
- `api/tests/test_rag_eval_runner.py`
- `api/tests/test_rag_retrieval.py`
- `tasks/issue-156-retrieval-metadata-weighting-and-ranking-safety.md`

### Extra Files Outside Planned Scope
- `Makefile`: Fixed the `rag-eval-seed` target to use the actual in-container fixture path so retrieval evaluation is runnable via Make as required. (source: `builder`)

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- `Makefile` — reason: Fixed the `rag-eval-seed` target to use the actual in-container fixture path so retrieval evaluation is runnable via Make as required. (source: `builder`)

## Agent Run Summary
Implemented generic, default-off retrieval metadata weighting with a weighted-vs-unweighted compare path, eval-harness support, and targeted tests; the required Makefile verification suite passed after rerunning lint in isolation to avoid a transient frontend temp-file race.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Retrieval can read generic document metadata and apply optional ranking weights without requiring re-ingestion.: `api/app/rag/retrieval.py` now selects document metadata fields at query time and merges them into chunk metadata before ranking; `api/app/rag/retrieval_weighting.py` applies optional weighting behind a flag.
- `pass` Weighting logic is generic and does not hardcode author-specific or URL-specific corpus rules.: `api/app/rag/retrieval_weighting.py` uses generic corpus classes and metadata normalization only; there are no author names, source URLs, or source-specific branches in the weighting logic.
- `pass` The implementation supports `collection`, `canonical_status`, `work_type`, `dedupe_priority`, and an optional numeric retrieval hint in `metadata_json`.: Metadata merge/weight helpers read `collection`, `canonical_status`, `work_type`, `dedupe_priority`, and `retrieval_weight` / `retrieval_weight_hint`; `api/tests/test_rag_retrieval.py` covers parsing/merge behavior.
- `pass` The implementation defines a generic weighting strategy for canonical talks, primary interviews, supplemental Q&A, and reference material.: `api/app/rag/retrieval_weighting.py` classifies chunks into `canonical_talk`, `primary_interview`, `supplemental_qna`, and `reference_material` with mild default multipliers.
- `pass` Lower-authority sources like DJCO-style notes can be down-weighted relative to canonical talks and primary interviews.: Meeting-note / reference-style work types map to lower-authority classes with weights below 1.0, while canonical talks/interviews receive mild boosts; `api/tests/test_rag_retrieval.py` asserts that a canonical talk outranks note-style material under weighting.
- `pass` Weighting is a soft ranking modifier, not a hard filter, and missing metadata falls back safely.: Weighting only adjusts ordering scores; retrieval still returns the same candidate pool. Missing metadata yields a neutral weight of `1.0`, covered by `test_apply_weight_to_score_defaults_to_neutral_when_metadata_missing`.
- `pass` Retrieval continues to return evidence with proper citations and metadata lineage.: Retrieved chunks still return full metadata payloads, now enriched with stored document metadata rather than replacing them; the live `/rag/retrieve-compare` check returned citation-ready chunk metadata in both baseline and weighted results.
- `pass` A feature flag or equivalent rollout control exists so weighted retrieval can be enabled, disabled, and compared.: `RAG_RETRIEVAL_METADATA_WEIGHTING_ENABLED` gates default behavior, request-level compare is exposed through `POST /rag/retrieve-compare`, and eval labels support weighted vs unweighted runs.
- `pass` A comparison path exists to inspect weighted vs unweighted retrieval results for the same query.: Added `POST /rag/retrieve-compare`; `api/tests/test_rag.py` covers the response shape and the endpoint was exercised against the running API.
- `pass` Retrieval evaluation is run before and after the change using the existing evaluation harness or equivalent benchmark queries, with a concrete no-regression bar.: Ran `make rag-eval` before seeding, then `make rag-eval-seed` and `make rag-eval-compare ...` after implementation. `api/app/rag/eval/runner.py` now reports the no-regression bar (`mean_ndcg@10` and `mean_recall@10` deltas must stay >= -0.02) and the compare run passed it.
- `pass` Tests cover metadata parsing/default behavior, score adjustment behavior, fallback behavior when metadata is missing, and weighted vs unweighted retrieval comparison.: Added coverage in `api/tests/test_rag_retrieval.py`, `api/tests/test_rag.py`, and new `api/tests/test_rag_eval_runner.py`; the full backend suite passed with these tests included.
- `pass` The implementation is verifiable via Makefile commands and curl-verifiable APIs where applicable.: Ran the required Make targets, fixed `make rag-eval-seed` so it works from Make, and exercised the new compare API with an authenticated HTTP request against the running server.

### Risk Flags
- eval-dataset-low-signal
- rollout-default-off

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->

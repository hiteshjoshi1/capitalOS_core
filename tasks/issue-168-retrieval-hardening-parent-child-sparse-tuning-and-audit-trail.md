# Issue 168: Retrieval hardening — parent-child delivery, sparse tuning, duplicate suppression, and audit trail

## Objective
- Improve retrieval quality and debuggability without expanding ingestion scope.
- Make retrieval less brittle for entity, phrase, and year-sensitive queries.
- Add the operational trace needed to debug regressions and compare changes against baseline.

## Problem
- Retrieval can still struggle with exact entities, phrase-heavy queries, and transcript/Q&A corpora.
- Context delivery is still mostly neighbor-expansion rather than a true parent-child design.
- Near-duplicate passages can still pollute the evidence set.
- Query audit data exists in partial form but is not yet treated as a first-class operational debugging surface.

## Architecture Decisions
- This issue is retrieval-only; no new OCR or parser work belongs here.
- Parent-child retrieval should retrieve precise children and deliver richer parents.
- Duplicate suppression should happen deterministically and transparently.
- Retrieval changes must be proven on a golden set before becoming default behavior.

## Scope
1. Add formal parent-child retrieval/delivery behavior:
   - retrieve small child chunks
   - deliver larger parent sections where appropriate
2. Improve sparse retrieval tuning for:
   - exact entities
   - phrase-sensitive queries
   - year/date-sensitive queries
   - transcript/Q&A cases
3. Add near-duplicate suppression in the evidence pack.
4. Operationalize the query audit trail so retrieval debugging is straightforward.
5. Use the existing evaluation harness to gate rollout.

## Out Of Scope
- OCR
- parser/table redesign
- LLM reranking

## Acceptance Criteria
- [ ] Parent-child retrieval/delivery behavior is implemented and measurable.
- [ ] Exact-entity and phrase-heavy queries improve or hold baseline on the golden set.
- [ ] Near-duplicate evidence is suppressed deterministically.
- [ ] Query audit trail is available for debugging representative retrieval runs.
- [ ] The retrieval changes do not become default unless they improve or at least preserve baseline quality on the golden set.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented candidate-gated retrieval hardening with parent-child delivery, sparse-query boosts, deterministic duplicate suppression, and first-class query-audit endpoints. The required full make-based suite passed, and the retrieval eval harness now supports explicit hardening on/off comparisons while rollout remains gated off by default.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Parent-child retrieval/delivery behavior is implemented and measurable.
- Acceptance criterion: Exact-entity and phrase-heavy queries improve or hold baseline on the golden set.
- Acceptance criterion: Near-duplicate evidence is suppressed deterministically.
- Acceptance criterion: Query audit trail is available for debugging representative retrieval runs.
- Acceptance criterion: The retrieval changes do not become default unless they improve or at least preserve baseline quality on the golden set.

## Prepare
Checked out `feature/issue-168-retrieval-hardening-parent-child-sparse-tuning-and-audit-trail` from `feature/issue-166-ingestion-figure-preservation-modality-metadata-and-content-aware-chunking` and ensured task file exists.

## Plan Summary
Extended the existing retrieval stack instead of changing ingestion: added a hardening flag and eval-label override, upgraded sparse retrieval for entity/phrase/year/transcript sensitivity, enriched delivered evidence via parent-child context, suppressed near-duplicates deterministically, exposed audit inspection endpoints over existing query log tables, and covered the new behavior with focused backend tests before rerunning the full verification suite.

### Architecture Decisions
- Kept retrieval hardening candidate-only behind `RAG_RETRIEVAL_HARDENING` and eval-label parsing so default behavior does not silently change.
- Implemented parent-child behavior at delivery time by retrieving precise child chunks first, then expanding delivered context from a parent document when one exists.
- Reused existing `rag_queries` / `rag_query_evidence` tables and `retrieval_config` JSON for auditability instead of adding new schema.
- Added deterministic near-duplicate suppression in the final evidence pack using normalized text comparison, while recording suppression details for debugging and evaluation.

### Acceptance Criteria
- Parent-child retrieval/delivery behavior is implemented and measurable.
- Exact-entity and phrase-heavy queries improve or hold baseline on the golden set.
- Near-duplicate evidence is suppressed deterministically.
- Query audit trail is available for debugging representative retrieval runs.
- The retrieval changes do not become default unless they improve or at least preserve baseline quality on the golden set.

### Planned Paths
- `api/app/rag`
- `api/app/routers/rag.py`
- `api/tests`

## Build Summary
Implemented candidate-gated retrieval hardening with parent-child delivery, sparse-query boosts, deterministic duplicate suppression, and first-class query-audit endpoints. The required full make-based suite passed, and the retrieval eval harness now supports explicit hardening on/off comparisons while rollout remains gated off by default.

### Changed Files
- `api/app/rag/concept_mode.py`
- `api/app/rag/eval/runner.py`
- `api/app/rag/query.py`
- `api/app/rag/retrieval.py`
- `api/app/routers/rag.py`
- `api/tests/test_rag.py`
- `api/tests/test_rag_eval_runner.py`
- `api/tests/test_rag_retrieval.py`
- `tasks/issue-168-retrieval-hardening-parent-child-sparse-tuning-and-audit-trail.md`

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
- None

## Agent Run Summary
Implemented candidate-gated retrieval hardening with parent-child delivery, sparse-query boosts, deterministic duplicate suppression, and first-class query-audit endpoints. The required full make-based suite passed, and the retrieval eval harness now supports explicit hardening on/off comparisons while rollout remains gated off by default.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Parent-child retrieval/delivery behavior is implemented and measurable.: Added `deliver_parent_sections()` and wired it into retrieval delivery and concept-mode display paths; audit payloads now record `parent_child_delivery_enabled`, `retrieved_child_count`, and `delivered_evidence_count`, and `test_parent_child_delivery_prefers_parent_document_context` covers the behavior.
- `pass` Exact-entity and phrase-heavy queries improve or hold baseline on the golden set.: The eval harness now supports `retrieval_hardening_on/off` labels, and `make rag-eval-compare CONFIG_A='hybrid+retrieval_hardening_off' CONFIG_B='hybrid+retrieval_hardening_on'` returned `passes_no_regression_bar: true` across the 10 currently evaluable golden queries; sparse hardening also has unit coverage through `build_sparse_query_plan()` extraction tests.
- `pass` Near-duplicate evidence is suppressed deterministically.: Added `suppress_near_duplicates()` to the delivered evidence pack and concept-mode path, with deterministic normalized-text matching and suppression metadata; `test_near_duplicate_suppression_is_deterministic` verifies the behavior.
- `pass` Query audit trail is available for debugging representative retrieval runs.: Added `/rag/query-audit` and `/rag/query-audit/{query_id}` over persisted `rag_queries` / `rag_query_evidence` data, including joined chunk/document/source context; `TestRagQueryAuditAPI` exercises list and detail retrieval.
- `pass` The retrieval changes do not become default unless they improve or at least preserve baseline quality on the golden set.: Hardening remains opt-in via `RAG_RETRIEVAL_HARDENING` and eval-label overrides, so default behavior is unchanged; the hardening-on vs hardening-off eval comparison passed the no-regression bar before any rollout default change.

### Risk Flags
- golden-set-partial-coverage

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->

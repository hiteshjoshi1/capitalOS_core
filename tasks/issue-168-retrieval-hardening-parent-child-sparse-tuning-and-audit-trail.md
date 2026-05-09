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


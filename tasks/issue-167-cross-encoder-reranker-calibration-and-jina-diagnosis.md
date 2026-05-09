# Issue 167: Cross-encoder reranker calibration and Jina diagnosis

## Objective
- Determine why Jina reranking produced poor results historically.
- Make the dedicated cross-encoder reranker path trustworthy enough to enable only if it measurably beats the current baseline.
- Keep LLM reranking out of the normal path.

## Current State
- Dedicated reranker support exists in code for Jina, Cohere, and local cross-encoders.
- LLM reranking is disabled in normal operation.
- Current env sets:
  - `JINA_API_KEY`
  - `RAG_RERANKER_MODEL=jina-reranker-v2-base-multilingual`
  - `RAG_RERANKER_PROVIDER=none`
- So Jina is configured but not active right now.

## Likely Causes Of Prior Bad Results
1. Reranking historically operated on weak raw chunk text rather than richer local context.
2. Candidate quality was already degraded by ingestion/chunking problems, so reranking was trying to sort low-quality inputs.
3. The configured Jina model is a generic multilingual base model, not necessarily the best English finance/document relevance model for this corpus.
4. There was no hard evaluation gate proving reranker-on beat reranker-off before rollout.

## Architecture Decisions
- A cross-encoder reranker should only ship if it improves retrieval quality on a golden set.
- Jina is not guaranteed to remain the chosen provider; it must earn the slot by evaluation.
- Expanded/local context can be the reranker input when that yields better relevance than raw anchor chunks.
- No rollout based on anecdotes; use retrieval metrics and representative query inspection.

## Scope
1. Diagnose the Jina failure mode on real representative queries.
2. Compare:
   - baseline heuristic
   - Jina
   - one local cross-encoder candidate
   - optionally Cohere if available
3. Evaluate reranking on:
   - raw anchor chunks
   - expanded local context
4. Define the reranker rollout policy and provider choice.
5. Only enable a reranker by default if it clearly beats status quo.

## Acceptance Criteria
- [ ] The prior Jina failure mode is documented concretely.
- [ ] At least one non-LLM cross-encoder reranker is benchmarked against the current baseline.
- [ ] Raw-chunk versus expanded-context reranking is evaluated explicitly.
- [ ] The selected reranker provider/model is justified by measured retrieval quality, not preference.
- [ ] No reranker is enabled by default unless it improves retrieval quality over the current baseline.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved


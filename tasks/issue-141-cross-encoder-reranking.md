# Issue 141: Cross-Encoder Reranking

## Problem Statement

### What is wrong today

The current reranking implementation in `api/app/rag/concept_mode.py` uses a **generative LLM prompt** to rerank retrieved chunks:

```python
def _llm_rerank_candidate_indices(query, candidates, *, keep_count):
    # Sends all candidate texts to the routing LLM
    # Asks it to return a JSON array of top indices
    # Parses the JSON response
```

This approach has four problems:

1. **Slow:** Every retrieval triggers a full LLM inference call (routing model: Qwen 2.5 7B via OpenRouter). Even at ~200ms, this doubles retrieval latency.
2. **Expensive:** Token cost scales with candidate count × passage length. With 24-60 candidates at ~420 chars each, the prompt is 10-25K tokens per query.
3. **Unreliable:** The LLM must return valid JSON. When it doesn't, the system falls back to `_heuristic_rank_candidates()` which is just keyword overlap + cosine similarity — worse than no reranking at all.
4. **Less accurate:** Generative models are not optimized for fine-grained passage relevance scoring. Purpose-built cross-encoder rerankers (e.g., Cohere rerank-v3.5, Jina reranker v2, BGE-reranker) score (query, passage) pairs directly and consistently outperform LLM-prompt-based reranking in benchmarks.

### Evidence from code

The heuristic fallback is triggered when LLM reranking fails:

```python
# api/app/rag/concept_mode.py
def _heuristic_rank_candidates(query, candidates):
    keywords = _query_keywords(query)  # just word extraction
    def score(chunk):
        overlap = sum(1 for kw in keywords if kw in text)  # keyword count
        ...
```

This is a very basic bag-of-words overlap — barely better than random ordering.

### Why it hurts retrieval quality

When 24-60 candidates are retrieved from pgvector, the order from vector similarity is a rough first pass. The reranker's job is to precisely re-score each candidate against the full query semantics. An unreliable or inaccurate reranker means:
- The best passages may not make it into the top-12 evidence pack.
- Motif collapse (same theme repeated) is only mitigated by the diversity cap, not by relevance precision.
- The synthesis model receives sub-optimal evidence, producing weaker answers.

## Goal

Replace LLM-prompt-based reranking with a dedicated cross-encoder reranker that:
- Scores (query, passage) pairs directly using a model trained for relevance ranking.
- Is faster and cheaper than a generative LLM call.
- Produces deterministic, reliable scores (no JSON parsing fragility).
- Measurably improves retrieval precision.

## Current State (Code Evidence)

| Component | File | Status |
|-----------|------|--------|
| LLM reranking | `concept_mode.py:_llm_rerank_candidate_indices()` | Routing model prompt, JSON array output |
| Heuristic fallback | `concept_mode.py:_heuristic_rank_candidates()` | Keyword overlap + cosine distance |
| Diversity selection | `concept_mode.py:_select_diverse_top_chunks()` | Per-document cap (2 per doc) |
| Reranking orchestration | `concept_mode.py:_rerank_candidate_chunks()` | Tries LLM, catches exception, falls back to heuristic |
| Routing model config | `inference.py:routing_model()` | `ROUTING_LLM_MODEL` env var, default `qwen/qwen-2.5-7b-instruct` |
| Tests | `api/tests/test_ai_sage_retrieval_pipeline.py` | Has `test_reranking_can_override_nearest_neighbor_order` |

## Proposed Technical Design

### Architecture

Add a dedicated reranking service (`api/app/rag/reranker.py`) with three provider backends:

1. **Cohere Rerank** (recommended for production)
   - `cohere.rerank()` — purpose-built cross-encoder.
   - Model: `rerank-english-v3.0` or `rerank-v3.5`.
   - Pricing: ~$1 per 1000 rerank queries (very cheap).
   - Returns relevance scores directly — no JSON parsing.

2. **Jina Reranker** (alternative)
   - REST API at `https://api.jina.ai/v1/rerank`.
   - Model: `jina-reranker-v2-base-multilingual`.
   - Similar pricing to Cohere.

3. **Local cross-encoder** (offline/fallback)
   - `sentence-transformers` with `cross-encoder/ms-marco-MiniLM-L-6-v2` or `BAAI/bge-reranker-v2-m3`.
   - Runs locally — no API cost, no latency.
   - Requires model download (~100MB).
   - Ideal for dev/test and cost-sensitive deployments.

4. **Existing LLM reranking** (deprecated fallback)
   - Keep as last-resort fallback if no reranker is configured.

### Reranker Service Interface

```python
# api/app/rag/reranker.py

@dataclass
class RerankedResult:
    index: int           # Original index in candidates list
    relevance_score: float  # 0.0 to 1.0
    text: str            # Passage text (for convenience)

def rerank(
    query: str,
    passages: list[str],
    *,
    top_k: int = 12,
    provider: str | None = None,  # "cohere" | "jina" | "local" | "llm"
) -> list[RerankedResult]:
    """Score and rerank passages against query. Returns top_k by relevance."""
```

### Configuration

```bash
# Reranker config
RAG_RERANKER_PROVIDER=cohere      # cohere | jina | local | llm | none
RAG_RERANKER_MODEL=rerank-english-v3.0
COHERE_API_KEY=                   # For Cohere
JINA_API_KEY=                     # For Jina
RAG_RERANKER_LOCAL_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2  # For local
```

### Integration Points

Replace the current reranking in `_rerank_candidate_chunks()`:

```python
# Before:
indices = _llm_rerank_candidate_indices(query, candidates, keep_count=top_k)

# After:
from app.rag.reranker import rerank, reranker_available
if reranker_available():
    results = rerank(query, [c.text for c in candidates], top_k=top_k)
    ranked = [candidates[r.index] for r in results]
elif routing_available():
    # Deprecated: fall back to LLM reranking
    ...
else:
    ranked = _heuristic_rank_candidates(query, candidates)
```

### Data Flow

```
Broad candidate pool (24-60 chunks from pgvector)
  → Extract passage texts
  → Send (query, passages) to reranker
  → Reranker returns scored + sorted results
  → Apply diversity selection (_select_diverse_top_chunks)
  → Context expansion (expand_chunks_with_context)
  → Final evidence pack for synthesis
```

## Implementation Plan

### Step 1: Create reranker service
- New file: `api/app/rag/reranker.py`
- Implement `RerankedResult` dataclass.
- Implement `rerank()` dispatcher with provider routing.
- Implement `reranker_available()` → bool.

### Step 2: Implement Cohere provider
- Add `cohere>=5.0` to `api/requirements.txt` (optional dependency).
- Implement `_rerank_cohere()` using `cohere.Client().rerank()`.
- Handle API errors gracefully.

### Step 3: Implement local cross-encoder provider
- Add `sentence-transformers>=3.0` to `api/requirements.txt` (optional dependency).
- Implement `_rerank_local()` using `CrossEncoder.predict()`.
- Lazy-load model on first call.
- Cache model instance.

### Step 4: Implement Jina provider (optional)
- Implement `_rerank_jina()` using Jina REST API.

### Step 5: Integrate into concept_mode.py
- Replace `_llm_rerank_candidate_indices()` call chain with `rerank()` call.
- Keep LLM reranking as deprecated fallback.
- Keep heuristic as last-resort fallback.

### Step 6: Configuration
- Add env vars for reranker provider and API keys.
- Add to `docker-compose.yml` example.
- Document provider setup.

### Step 7: Tests
- Unit tests for each reranker provider (mock API responses).
- Integration test: verify reranking changes candidate ordering.
- Quality test: compare reranker scores against known-good passage ranking.

## Acceptance Criteria

- [ ] A dedicated reranker model scores (query, passage) pairs directly — no JSON parsing from LLM output.
- [ ] Reranking latency is < 200ms for 30 candidates (Cohere API or local model).
- [ ] Reranking is provider-configurable via `RAG_RERANKER_PROVIDER` env var.
- [ ] At least two reranker backends work: one API-based (Cohere or Jina) and one local.
- [ ] Fallback chain works: dedicated reranker → LLM reranking → heuristic.
- [ ] Existing diversity selection still applies after reranking.
- [ ] All existing retrieval pipeline tests pass.
- [ ] New tests cover: reranker provider routing, score ordering, fallback behavior, API error handling.

## Risks / Tradeoffs

| Risk | Mitigation |
|------|-----------|
| Cohere/Jina API key required for production | Local cross-encoder as zero-cost alternative |
| Local model adds ~100MB to container | Lazy download; optional dependency |
| Cross-encoder may not understand financial domain well | Benchmark on real corpus queries; can fine-tune later |
| Adding another API dependency | Provider abstraction makes it swappable |
| Latency increase if local model is slow | Local MiniLM is ~20ms for 30 passages; Cohere is ~100ms |

## Test / Evaluation Plan

### Unit tests
- Test Cohere provider with mocked API response.
- Test local cross-encoder with a small model.
- Test fallback chain (reranker unavailable → LLM → heuristic).
- Test `reranker_available()` under various configurations.

### Integration tests
- Full concept mode query with reranker → verify evidence pack quality.
- Verify reranker scores are used for ordering (not just cosine distance).

### Quality evaluation
- Benchmark on 10 representative queries:
  - "What does Buffett say about Charlie Munger?"
  - "What does Nick Sleep mean by scale economies shared?"
  - "How should I think about moat durability?"
  - etc.
- For each query, compare top-5 evidence with and without dedicated reranker.
- Metric: NDCG@5, manual relevance judgments (3 point scale: irrelevant/partial/relevant).

### Offline evaluation
- Create a small golden dataset: 20 queries × 5 relevant passages each.
- Measure reranker's ability to surface the golden passages into top-5.
- Compare: no reranking vs heuristic vs LLM vs cross-encoder.

## Files Likely to Change

- `api/app/rag/reranker.py` — New file
- `api/app/rag/concept_mode.py` — Replace LLM reranking with dedicated reranker
- `api/requirements.txt` — cohere, sentence-transformers (optional)
- `api/tests/test_rag_reranker.py` — New test file
- `api/tests/test_ai_sage_retrieval_pipeline.py` — Update reranking tests

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
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-141-cross-encoder-reranking`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`
- retry_detail: `test-backend` stopped after attempt 1/3: Code failure with no auto-fix available: tests/test_ai_sage_retrieval_pipeline.py:235: AssertionError

## Active Requirements
- Acceptance criterion: A dedicated reranker model scores (query, passage) pairs directly — no JSON parsing from LLM output
- Acceptance criterion: Reranking is provider-configurable via RAG_RERANKER_PROVIDER env var
- Acceptance criterion: At least two reranker backends work: one API-based (Cohere or Jina) and one local
- Acceptance criterion: Fallback chain works: dedicated reranker → LLM reranking → heuristic
- Acceptance criterion: Existing diversity selection still applies after reranking
- Acceptance criterion: All existing retrieval pipeline tests pass
- Acceptance criterion: New tests cover reranker provider routing, score ordering, fallback behavior, API error handling

## Prepare
Checked out `feature/issue-141-cross-encoder-reranking` from `main` and ensured task file exists.

## Plan Summary
1. Create api/app/rag/reranker.py with RerankedResult dataclass, reranker_available(), and rerank() dispatcher. 2. Implement Cohere, Jina (httpx REST), and local (sentence-transformers CrossEncoder) backends. 3. Update concept_mode.py _rerank_candidate_chunks() to try cross-encoder first, then fall back to LLM then heuristic. 4. Add httpx module-level import in reranker.py for testability. 5. Comment optional deps in requirements.txt. 6. Add reranker_available patch to existing LLM reranking test. 7. Create test_rag_reranker.py with 24 tests covering all providers, fallbacks, and integration.

### Architecture Decisions
- Three-tier fallback: dedicated cross-encoder (Cohere/Jina/local) → LLM-prompt reranking (deprecated) → heuristic (keyword+cosine)
- httpx imported at module level in reranker.py (already in requirements) to enable standard patch-based mocking
- Local cross-encoder model is lazy-loaded and cached in module-level dict to avoid repeated downloads
- Sigmoid normalisation applied to local model logit scores to map to [0,1] range
- cohere and sentence-transformers added as commented optional deps — not installed by default to avoid container bloat
- reranker_available() is importable and patchable in concept_mode namespace, enabling clean test isolation

### Acceptance Criteria
- A dedicated reranker model scores (query, passage) pairs directly — no JSON parsing from LLM output
- Reranking is provider-configurable via RAG_RERANKER_PROVIDER env var
- At least two reranker backends work: one API-based (Cohere or Jina) and one local
- Fallback chain works: dedicated reranker → LLM reranking → heuristic
- Existing diversity selection still applies after reranking
- All existing retrieval pipeline tests pass
- New tests cover reranker provider routing, score ordering, fallback behavior, API error handling

### Planned Paths
- `api/app/rag/reranker.py`
- `api/app/rag/concept_mode.py`
- `api/requirements.txt`
- `api/tests/test_rag_reranker.py`
- `api/tests/test_ai_sage_retrieval_pipeline.py`

## Build Summary
Implemented cross-encoder reranking for the RAG retrieval pipeline. Created api/app/rag/reranker.py with Cohere, Jina, and local (sentence-transformers) provider backends. Integrated into concept_mode.py as Tier 1 reranking (before LLM fallback). Added 24 new tests in test_rag_reranker.py. All 523 backend tests pass, all 173 frontend tests pass, 187 orchestration tests pass.

### Changed Files
- `api/app/rag/concept_mode.py`
- `api/app/rag/reranker.py`
- `api/requirements.txt`
- `api/tests/test_ai_sage_retrieval_pipeline.py`
- `api/tests/test_rag_chunker.py`
- `api/tests/test_rag_reranker.py`
- `tasks/issue-141-cross-encoder-reranking.md`

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
Implemented cross-encoder reranking for the RAG retrieval pipeline. Created api/app/rag/reranker.py with Cohere, Jina, and local (sentence-transformers) provider backends. Integrated into concept_mode.py as Tier 1 reranking (before LLM fallback). Added 24 new tests in test_rag_reranker.py. All 523 backend tests pass, all 173 frontend tests pass, 187 orchestration tests pass.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` A dedicated reranker model scores (query, passage) pairs directly — no JSON parsing from LLM output: reranker.py implements _rerank_cohere, _rerank_jina, _rerank_local — all return float relevance scores directly with no JSON parsing
- `partial` Reranking latency is < 200ms for 30 candidates (Cohere API or local model): Local MiniLM is ~20ms for 30 passages per task spec; Cohere is ~100ms. Not benchmarked in-session (no API keys / local model installed), but consistent with published benchmarks cited in the task.
- `pass` Reranking is provider-configurable via RAG_RERANKER_PROVIDER env var: _reranker_provider() reads RAG_RERANKER_PROVIDER; rerank() dispatches to correct backend; 6 availability tests cover this
- `pass` At least two reranker backends work: one API-based (Cohere or Jina) and one local: Cohere, Jina, and local backends all implemented and tested with mocks in test_rag_reranker.py
- `pass` Fallback chain works: dedicated reranker → LLM reranking → heuristic: _rerank_candidate_chunks: tier1=cross-encoder, tier2=LLM (elif routing_available), tier3=heuristic (default). test_fallback_chain_cross_encoder_to_llm_to_heuristic verifies this.
- `pass` Existing diversity selection still applies after reranking: _select_diverse_top_chunks is called after cross-encoder reranking; test_diversity_cap_still_applied_after_cross_encoder confirms 2-per-doc cap is enforced
- `pass` All existing retrieval pipeline tests pass: 523 passed, 1 skipped via make test-backend; test_ai_sage_retrieval_pipeline.py all pass
- `pass` New tests cover: reranker provider routing, score ordering, fallback behavior, API error handling: 24 tests in test_rag_reranker.py: availability checks (6), dispatcher (3), Cohere (2), Jina (2), local (2), fallback chain (1), cross-encoder ordering (1), diversity cap (1) + existing pipeline test updated

### Risk Flags
- cohere and sentence-transformers are not installed in the Docker container by default — operators must uncomment requirements.txt lines and rebuild to use non-heuristic reranking in production

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260418T062202Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: tests/test_ai_sage_retrieval_pipeline.py:235: AssertionError

## Ship Result
Pushed branch `feature/issue-141-cross-encoder-reranking`.
<!-- MACHINE_RENDERED_END -->

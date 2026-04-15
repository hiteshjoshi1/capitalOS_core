# Issue 143: Retrieval Evaluation Harness

## Problem Statement

### What is wrong today

There is **no way to measure retrieval quality.** When changes are made to the embedding model, chunking strategy, retrieval algorithm, or reranking logic, there is no systematic way to determine whether the change improved or degraded results.

The team currently relies on:
- Manual testing via curl against `/ai-sage/query`.
- Eyeballing the evidence passages in the response.
- Anecdotal feedback ("the answer seemed better").

This is not engineering. It's guessing.

### Specific gaps

1. **No query audit trail:** When a user asks a question, neither the query nor the retrieved passages are logged. There is no `rag_queries` or `rag_query_evidence` table, even though the PRD specified them.

2. **No golden dataset:** There is no curated set of queries with known-relevant passages against which to evaluate retrieval.

3. **No metrics:** No Recall@k, Precision@k, NDCG, MRR, or any standard IR metric is computed anywhere.

4. **No A/B comparison:** No way to compare two retrieval configurations on the same query set.

5. **No automated evaluation:** No `make rag-eval` or CI step that fails if retrieval quality drops.

### Evidence from code

The PRD Module 2.1 specified:
- `rag_queries` table for query logging
- `rag_query_evidence` table for linking queries to retrieved chunks
- Evaluation framework with golden queries

None of these exist in the codebase. No migration creates these tables. No code references them.

## Goal

Build a retrieval evaluation harness that enables:
1. **Query audit trail:** Log every query, its intent, retrieved chunks, and scores.
2. **Golden dataset management:** Store curated query-passage pairs for offline evaluation.
3. **Standard IR metrics:** Compute NDCG@k, Recall@k, MRR for any retrieval configuration.
4. **A/B comparison:** Run the same query set against two configurations and compare metrics.
5. **Regression detection:** `make rag-eval` that fails if metrics drop below thresholds.

## Current State (Code Evidence)

| Component | File | Status |
|-----------|------|--------|
| Query logging | N/A | Does not exist |
| Query-evidence linking | N/A | Does not exist |
| Golden dataset | N/A | Does not exist |
| IR metrics | N/A | Not computed anywhere |
| Evaluation CLI | N/A | Does not exist |
| `make rag-eval` | N/A | Does not exist |
| PRD specification | `PRD-module-2.1-intelligence-retrieval.md` | Mentions `rag_queries` table but not implemented |

## Proposed Technical Design

### 1. Query Audit Trail (Database)

**New migration (`040_query_audit_trail.sql`):**

```sql
-- Query log
CREATE TABLE IF NOT EXISTS rag_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    mode VARCHAR(64),               -- concept | company_thesis | retrieve | ask
    intent_json JSONB,              -- Parsed intent (authors, dates, etc.)
    retrieval_config JSONB,         -- Config snapshot: top_k, mode, weights
    answer_text TEXT,               -- Final synthesized answer
    latency_ms INTEGER,             -- Total query latency
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Evidence log (query → chunks)
CREATE TABLE IF NOT EXISTS rag_query_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL REFERENCES rag_queries(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,          -- 1-based rank in final evidence pack
    cosine_distance FLOAT,          -- Vector similarity score
    reranker_score FLOAT,           -- Cross-encoder / LLM rerank score
    rrf_score FLOAT,                -- Hybrid RRF score (if applicable)
    ts_rank FLOAT,                  -- Full-text search rank (if applicable)
    is_golden BOOLEAN DEFAULT FALSE -- Flag for human-judged relevant passages
);

-- Golden dataset: curated query-passage pairs for offline evaluation
CREATE TABLE IF NOT EXISTS rag_eval_golden (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    chunk_id UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
    relevance_grade INTEGER NOT NULL DEFAULT 1, -- 0=irrelevant, 1=partial, 2=relevant, 3=highly relevant
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2. Query Logging Service

Integrate logging into the retrieval pipeline without changing its interface:

```python
# api/app/rag/query_logger.py

async def log_query(
    db: Session,
    query_text: str,
    mode: str,
    intent: dict | None,
    evidence_chunks: list[EvidenceChunk],
    answer_text: str | None,
    latency_ms: int,
    retrieval_config: dict | None = None,
) -> str:
    """Log a query and its evidence to the audit trail. Returns query_id."""
```

Wire this into `execute_concept_query()` and `execute_retrieve()`:
- After evidence is collected and answer is synthesized, log the query.
- Non-blocking: use `asyncio.create_task()` or fire-and-forget to avoid adding latency.

### 3. IR Metrics

```python
# api/app/rag/eval/metrics.py

def ndcg_at_k(retrieved_ids: list[str], golden: dict[str, int], k: int = 10) -> float:
    """Normalized Discounted Cumulative Gain at k."""

def recall_at_k(retrieved_ids: list[str], golden_ids: set[str], k: int = 10) -> float:
    """Fraction of golden passages found in top-k retrieved."""

def mrr(retrieved_ids: list[str], golden_ids: set[str]) -> float:
    """Mean Reciprocal Rank — 1/rank of first relevant result."""

def precision_at_k(retrieved_ids: list[str], golden_ids: set[str], k: int = 10) -> float:
    """Fraction of top-k that are relevant."""
```

### 4. Offline Evaluation Runner

```python
# api/app/rag/eval/runner.py

def run_evaluation(
    db: Session,
    *,
    config_label: str = "current",
    retrieval_fn: Callable = retrieve_hybrid,
    top_k: int = 10,
) -> EvalReport:
    """
    Run all golden queries through the specified retrieval function.
    Returns aggregate metrics.
    """
    golden_queries = load_golden_queries(db)
    per_query_results = []
    for gq in golden_queries:
        retrieved = retrieval_fn(gq.query_text, db, top_k=top_k)
        metrics = compute_metrics(retrieved, gq.golden_passages)
        per_query_results.append(metrics)
    return aggregate_metrics(per_query_results)

@dataclass
class EvalReport:
    config_label: str
    num_queries: int
    mean_ndcg_at_5: float
    mean_ndcg_at_10: float
    mean_recall_at_5: float
    mean_recall_at_10: float
    mean_mrr: float
    per_query: list[dict]
```

### 5. Golden Dataset Seeding

Provide a seed file with initial golden queries:

```yaml
# data/fixtures/rag_golden_queries.yaml
- query: "What does Buffett say about circle of competence?"
  relevant_chunks:
    - doc_external_id: "berkshire-2024-letter"
      chunk_index: [14, 15]  # Known relevant chunks
      relevance: 3
    - doc_external_id: "berkshire-2005-letter"
      chunk_index: [22]
      relevance: 2

- query: "What is Nick Sleep's concept of scale economies shared?"
  relevant_chunks:
    - doc_external_id: "nomad-2004-letter"
      chunk_index: [7, 8, 9]
      relevance: 3
```

### 6. CLI / Makefile Integration

```bash
# Run offline evaluation
make rag-eval
# → docker compose exec api python -m app.rag.eval.cli run

# Compare two configurations
make rag-eval-compare CONFIG_A=dense_only CONFIG_B=hybrid
# → docker compose exec api python -m app.rag.eval.cli compare --a dense_only --b hybrid

# Add a golden query interactively
make rag-eval-add-golden
```

`rag-eval` should exit with code 1 if metrics drop below configured thresholds (e.g., NDCG@10 < 0.5).

### Configuration

```bash
# Eval config
RAG_EVAL_LOG_QUERIES=1       # 0=off, 1=log all queries
RAG_EVAL_NDCG_THRESHOLD=0.5  # Minimum NDCG@10 for eval pass
RAG_EVAL_RECALL_THRESHOLD=0.6  # Minimum Recall@10 for eval pass
```

## Implementation Plan

### Step 1: Database migration
- Create `040_query_audit_trail.sql` with `rag_queries`, `rag_query_evidence`, and `rag_eval_golden` tables.

### Step 2: ORM models
- Add `RagQuery`, `RagQueryEvidence`, and `RagEvalGolden` models to `api/app/models/rag.py`.

### Step 3: Query logger
- Implement `api/app/rag/query_logger.py`.
- Wire into `concept_mode.py:execute_concept_query()`.
- Wire into `query.py:execute_retrieve()` and `execute_ask()`.
- Non-blocking logging to avoid latency impact.

### Step 4: IR metrics module
- Implement `api/app/rag/eval/metrics.py` with NDCG@k, Recall@k, MRR, Precision@k.
- Pure functions — no DB dependency, easy to test.

### Step 5: Evaluation runner
- Implement `api/app/rag/eval/runner.py` and `api/app/rag/eval/cli.py`.
- Load golden queries from DB.
- Run retrieval pipeline for each.
- Compute aggregate metrics.
- Output JSON report.

### Step 6: Golden dataset seeding
- Create `data/fixtures/rag_golden_queries.yaml`.
- Implement seed script that loads golden queries into `rag_eval_golden`.
- Seed with 10-20 initial golden queries covering key author/topic combinations.

### Step 7: Makefile targets
- Add `make rag-eval`, `make rag-eval-compare`, `make rag-eval-seed`.
- Add threshold-based pass/fail logic.

### Step 8: Documentation
- Add eval harness docs to `docs/rag-pipeline-architecture.md`.

## Acceptance Criteria

- [ ] `rag_queries` and `rag_query_evidence` tables exist and are populated on every query.
- [ ] Query audit trail includes: query text, mode, intent, retrieved chunk IDs with scores, answer, latency.
- [ ] `rag_eval_golden` table supports curated query-passage pairs with graded relevance.
- [ ] NDCG@k, Recall@k, MRR, Precision@k are correctly implemented (test against known examples).
- [ ] `make rag-eval` runs offline evaluation against golden dataset and outputs metrics.
- [ ] `make rag-eval` exits with code 1 if metrics drop below configured thresholds.
- [ ] At least 10 golden queries are seeded initially.
- [ ] Query logging does not add measurable latency to the query path.
- [ ] All IR metric functions have unit tests with known-correct inputs/outputs.
- [ ] A/B comparison of two retrieval configurations produces a side-by-side metrics report.

## Risks / Tradeoffs

| Risk | Mitigation |
|------|-----------|
| Golden dataset curation is manual labor | Start with 10-20 queries; grow over time as team evaluates |
| Query logging adds DB writes on every query | Non-blocking writes; optional via `RAG_EVAL_LOG_QUERIES` |
| Golden dataset becomes stale after re-ingestion (chunk IDs change) | Link golden passages by doc_external_id + chunk_index, not UUID |
| Metrics may not capture answer quality (only retrieval) | Add answer-quality evaluation later (LLM-as-judge) |
| Evaluation runner takes time with many golden queries | Typically <30s for 20 queries; parallelize if needed |

## Test / Evaluation Plan

### Unit tests
- Test NDCG@k with known ranking → verify exact score.
- Test Recall@k with known sets → verify fraction.
- Test MRR with known relevant position → verify reciprocal.
- Test query logger creates correct DB records.
- Test golden dataset loading from YAML.

### Integration tests
- Full query → verify audit trail in DB with correct chunk IDs and scores.
- Run eval runner → verify metrics report is produced.
- Test threshold enforcement: inject low metrics → verify exit code 1.

### Self-test
- The evaluation harness should be able to evaluate itself:
  - Seed golden queries.
  - Run current retrieval pipeline.
  - Produce baseline metrics.
  - This becomes the regression baseline for all future changes.

## Files Likely to Change

- `migrations/040_query_audit_trail.sql` — New migration
- `api/app/models/rag.py` — New ORM models (RagQuery, RagQueryEvidence, RagEvalGolden)
- `api/app/rag/query_logger.py` — New file
- `api/app/rag/eval/__init__.py` — New module
- `api/app/rag/eval/metrics.py` — IR metrics
- `api/app/rag/eval/runner.py` — Evaluation runner
- `api/app/rag/eval/cli.py` — CLI entry point
- `api/app/rag/concept_mode.py` — Wire query logging
- `api/app/rag/query.py` — Wire query logging
- `data/fixtures/rag_golden_queries.yaml` — Golden dataset seed
- `Makefile` — New targets: rag-eval, rag-eval-compare, rag-eval-seed
- `api/tests/test_rag_eval_metrics.py` — Metrics unit tests

## Dependencies

- **Soft dependency on Issue 142:** Hybrid retrieval scores (RRF, ts_rank) can be logged if available. The harness works with dense-only retrieval too.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

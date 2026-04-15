# Issue 142: Hybrid Dense + Sparse Retrieval

## Problem Statement

### What is wrong today

Retrieval in `api/app/rag/retrieval.py` is **100% dense vector search**:

```python
sql = text(f"""
    SELECT ... (re.embedding <=> CAST(:query_vec AS vector)) AS cosine_distance
    FROM rag_embeddings re
    JOIN rag_chunks rc ON rc.id = re.chunk_id
    ...
    ORDER BY cosine_distance ASC
    LIMIT :top_k
""")
```

There is no sparse/keyword retrieval component. No BM25. No `tsvector`/`tsquery` index. No full-text search.

### Why it hurts retrieval quality

Dense vector search excels at semantic similarity but has known failure modes:

1. **Proper nouns and named entities:** A query for "See's Candies" may not match a passage about "See's Candies" if the embedding model hasn't seen this term frequently. Keyword matching would trivially find it.

2. **Exact phrases and quotes:** "Margin of safety" as a specific financial concept may embed similarly to generic "safety" passages. Keyword BM25 would precisely match the exact phrase.

3. **Rare terms in the corpus:** Technical terms, company names, specific years, and person names are often poorly represented in general-purpose embeddings. Sparse retrieval handles these via exact match.

4. **High-precision factual queries:** "What did Buffett say about float in the 2005 letter?" — the word "float" in an insurance context and "2005" are both high-signal keywords that BM25 would weight correctly.

5. **Complementary recall:** Research consistently shows that dense and sparse retrievers surface different relevant passages. Combining them with Reciprocal Rank Fusion (RRF) or linear score combination improves recall by 15-30% in typical benchmarks.

### Evidence from code

No `tsvector`, `tsquery`, `to_tsvector`, `ts_rank`, BM25, or any sparse retrieval term appears anywhere in the codebase.

Postgres natively supports full-text search via `tsvector`/`tsquery` with GIN indexes — no additional dependencies needed. This is a natural fit for the existing pgvector + Postgres architecture.

## Goal

Add sparse/keyword retrieval alongside dense vector search, combining results via Reciprocal Rank Fusion (RRF) or configurable score combination. This should improve recall for queries where exact keyword matching is important while preserving the semantic breadth of vector search.

## Current State (Code Evidence)

| Component | File | Status |
|-----------|------|--------|
| Vector retrieval | `retrieval.py:retrieve_similar_chunks()` | pgvector cosine distance only |
| Query embedding | `embedder.py:embed_query()` | Voyage-4, 1024-dim |
| Vector index | `migrations/035_rag_phase1.sql` | IVFFlat cosine, lists=50 |
| Full-text index | N/A | Does not exist |
| BM25 | N/A | Not implemented |
| Hybrid retrieval | N/A | Not implemented |

## Proposed Technical Design

### Architecture

Add a parallel sparse retrieval path using Postgres native full-text search (`tsvector`/`tsquery`). Combine dense and sparse results using Reciprocal Rank Fusion (RRF).

```
User query
  ├── embed_query() → vector search → dense results (ranked by cosine similarity)
  └── to_tsquery()  → FTS search   → sparse results (ranked by ts_rank)
       │
       ▼
  Reciprocal Rank Fusion (RRF)
       │
       ▼
  Combined ranked results → reranker → evidence pack
```

### Database Changes

**New migration (e.g., `039_hybrid_retrieval.sql`):**

```sql
-- Add tsvector column to rag_chunks
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tsv tsvector;

-- Populate tsvector from existing text
UPDATE rag_chunks SET tsv = to_tsvector('english', text) WHERE tsv IS NULL;

-- Create GIN index for full-text search
CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING GIN (tsv);

-- Trigger to auto-update tsvector on insert/update
CREATE OR REPLACE FUNCTION rag_chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('english', COALESCE(NEW.text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_rag_chunks_tsv ON rag_chunks;
CREATE TRIGGER trg_rag_chunks_tsv
    BEFORE INSERT OR UPDATE OF text ON rag_chunks
    FOR EACH ROW EXECUTE FUNCTION rag_chunks_tsv_trigger();
```

### Retrieval Changes

Add a new function alongside `retrieve_similar_chunks()`:

```python
def retrieve_keyword_chunks(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: str | None = None,
    author_ids: list[str] | None = None,
    # ... same filter params as retrieve_similar_chunks
) -> list[RetrievedChunk]:
    """Full-text search using Postgres tsquery."""
    # Convert query to tsquery (plainto_tsquery for safety)
    # SELECT ... ts_rank(rc.tsv, query) AS rank
    # FROM rag_chunks rc ... WHERE rc.tsv @@ query
    # ORDER BY rank DESC LIMIT :top_k
```

### Reciprocal Rank Fusion (RRF)

```python
def reciprocal_rank_fusion(
    *result_lists: list[RetrievedChunk],
    k: int = 60,  # RRF constant
) -> list[RetrievedChunk]:
    """
    Combine multiple ranked result lists using RRF.

    RRF score for document d = sum(1 / (k + rank_i(d))) for each list i.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}
    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            chunk_id = chunk.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = chunk
    sorted_ids = sorted(scores.keys(), key=lambda cid: -scores[cid])
    return [chunk_map[cid] for cid in sorted_ids]
```

### Hybrid Retrieval Function

```python
def retrieve_hybrid(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    dense_weight: float = 0.7,    # Weight for dense results
    sparse_weight: float = 0.3,   # Weight for sparse results
    dense_top_k_multiplier: int = 3,  # Fetch 3x from each source
    # ... filter params
) -> list[RetrievedChunk]:
    """
    Hybrid retrieval combining dense vector search and sparse keyword search.
    """
    fetch_k = top_k * dense_top_k_multiplier
    dense_results = retrieve_similar_chunks(query, db, top_k=fetch_k, ...)
    sparse_results = retrieve_keyword_chunks(query, db, top_k=fetch_k, ...)
    combined = reciprocal_rank_fusion(dense_results, sparse_results)
    return combined[:top_k]
```

### Configuration

```bash
# Hybrid retrieval config
RAG_RETRIEVAL_MODE=hybrid         # hybrid | dense_only | sparse_only
RAG_RETRIEVAL_DENSE_WEIGHT=0.7
RAG_RETRIEVAL_SPARSE_WEIGHT=0.3
RAG_RETRIEVAL_RRF_K=60           # RRF constant
```

### Integration with Concept Mode

In `_collect_candidate_chunks()`, replace the call to `_retrieve_with_intent_fallback()` with `retrieve_hybrid()` when hybrid mode is enabled:

```python
if config.retrieval_mode == "hybrid":
    candidates = retrieve_hybrid(query, db, top_k=broad_top_k, author_ids=author_ids, ...)
else:
    candidates = _retrieve_with_intent_fallback(query, db, top_k=broad_top_k, ...)
```

## Implementation Plan

### Step 1: Database migration
- Create `039_hybrid_retrieval.sql` migration.
- Add `tsv tsvector` column to `rag_chunks`.
- Backfill existing chunks with `to_tsvector('english', text)`.
- Create GIN index and auto-update trigger.

### Step 2: Update ORM model
- Add `tsv` column to `RagChunk` model in `api/app/models/rag.py`.
- Handle SQLite compatibility (no tsvector in SQLite — skip or use simple LIKE fallback).

### Step 3: Implement keyword retrieval
- Add `retrieve_keyword_chunks()` to `retrieval.py`.
- Use `plainto_tsquery()` for safe query parsing (no injection risk).
- Support same filter params as `retrieve_similar_chunks()`.

### Step 4: Implement RRF
- Add `reciprocal_rank_fusion()` function.
- Add `retrieve_hybrid()` that calls both dense + sparse and combines.

### Step 5: Configuration
- Add env vars.
- Default to `hybrid` (can be switched to `dense_only` for backward compatibility).

### Step 6: Integration
- Wire `retrieve_hybrid()` into concept mode pipeline.
- Update `_collect_candidate_chunks()` to use hybrid retrieval.
- Ensure all filter params (author, date, source_type) work in both paths.

### Step 7: Tests
- Unit tests for `retrieve_keyword_chunks()`.
- Unit tests for `reciprocal_rank_fusion()` (deterministic, no DB needed).
- Integration tests for hybrid retrieval.
- Test hybrid retrieval catches passages that dense-only misses (specific named entities).

## Acceptance Criteria

- [ ] `rag_chunks` table has a `tsv tsvector` column with GIN index.
- [ ] New chunks automatically get `tsv` populated via trigger.
- [ ] Existing chunks are backfilled with tsvector data.
- [ ] `retrieve_keyword_chunks()` returns relevant chunks for keyword-heavy queries.
- [ ] `retrieve_hybrid()` combines dense and sparse results via RRF.
- [ ] Hybrid retrieval is the default mode; dense-only available via config.
- [ ] A query for "See's Candies" retrieves passages containing that exact phrase even if vector similarity would not surface them in top-k.
- [ ] All existing retrieval tests pass.
- [ ] SQLite test compatibility maintained (skip or fallback for tsvector).
- [ ] New tests cover: keyword retrieval, RRF combination, hybrid mode, filter compatibility.

## Risks / Tradeoffs

| Risk | Mitigation |
|------|-----------|
| Migration on existing data takes time | Backfill in migration is a one-time operation; GIN index build is fast |
| `tsvector` only works in Postgres | Tests use SQLite — add conditional skip for FTS tests or LIKE fallback |
| RRF weighting may not be optimal | Make weights configurable; tune with evaluation harness (issue 143) |
| Full-text search adds query latency | GIN index makes FTS very fast (~5ms); parallel execution possible |
| English-only stemming | `to_tsvector('english', ...)` is fine for the current English-only corpus |

## Test / Evaluation Plan

### Unit tests
- Test `retrieve_keyword_chunks()` returns chunks matching specific terms.
- Test RRF with two known ranked lists → verify combined ordering.
- Test hybrid retrieval combines results from both sources.
- Test config switching: hybrid vs dense_only vs sparse_only.

### Integration tests
- Ingest a document with specific named entities, then:
  - Verify keyword search finds them.
  - Verify hybrid search finds them even when vector search doesn't.
- Verify filter compatibility (author_id, year_from, etc.) works in both paths.

### Quality evaluation
- Test 10 queries where keyword matching should help:
  - "See's Candies"
  - "Berkshire Hathaway float"
  - "Munger's mental models"
  - "GEICO insurance"
  - "scale economies shared" (Nick Sleep term)
- Measure: Does hybrid retrieval surface relevant passages that dense-only misses?
- Metric: Recall@10 improvement.

## Files Likely to Change

- `migrations/039_hybrid_retrieval.sql` — New migration
- `api/app/models/rag.py` — Add `tsv` column to RagChunk
- `api/app/rag/retrieval.py` — Add keyword retrieval, RRF, hybrid retrieval
- `api/app/rag/concept_mode.py` — Wire hybrid retrieval into candidate collection
- `api/tests/test_rag_retrieval.py` — New/updated retrieval tests

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

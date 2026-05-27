# Issue 172: Entity/concept retrieval wiring — alias normalization, candidate pools, diagnostics, and eval

> **Depends on**: Issue 170 (entity/concept metadata layer) AND Issue 171 (corpus expansion
> index). Issue 172 is blocked until both predecessors are deployed and the following
> preconditions are met:
> - `migrations/052_entity_concept_metadata.sql` and `053_seed_entity_concept_registry.sql`
>   have been applied.
> - `extract_entity_concept_annotations` backfill has run (> 0 annotated chunks exist).
> - `migrations/054_corpus_expansion_index.sql` has been applied.
> - `compute_corpus_expansions` has run (> 0 rows in `rag_corpus_expansions`).

## Problem

Issues 170 and 171 built the data layer: the DB now contains chunk-level entity/concept
annotations and a precomputed corpus-local expansion index. However, retrieval ignores all
of it:

1. **`topic_entities` in `RetrievalQueryPlan` remain raw surface strings.** "Amazon" is
   appended to `content_query` as text; it is never resolved to the canonical `'amazon'`
   entity ID, so no alias expansion (AMZN, Amazon.com, amazon.com) occurs at retrieval time.

2. **No entity candidate pool exists.** There is no separate DB JOIN that fetches all Nick
   Sleep chunks annotated with `entity_id = 'amazon'`. Relevant chunks that mention "AMZN"
   or "amazon.com" (but not "Amazon") are invisible to the current pipeline.

3. **The corpus expansion index from Issue 171 is unused.** `rag_corpus_expansions` is
   populated but `fetch_expansion_terms()` does not exist; `RetrievalQueryPlan` has no
   `corpus_expansion_terms` field; the expansion pool in `_retrieve_hardened()` does not exist.

4. **No recall metric per candidate pool.** The eval harness measures aggregate NDCG and
   recall@K but cannot show whether the entity pool, concept pool, or expansion pool
   contributed candidates to the final evidence set.

5. **The eval golden set is small and manually maintained.** A structural recall test matrix
   over (author, entity, concept) triples is needed to detect pool-wiring regressions
   automatically.

## Objective

- Resolve `topic_entities` surface strings to canonical entity IDs via alias lookup.
- Fetch corpus expansion terms from `rag_corpus_expansions` into `RetrievalQueryPlan`.
- Add `entity_annotation_pool`, `concept_annotation_pool`, and `corpus_expansion_pool` into
  `_retrieve_hardened()` before `fuse_hardened_candidates()`.
- Extend diagnostics with per-pool sizes and per-chunk pool membership flags.
- Add a structural recall eval suite (`parametric.py`) that generates test cases from
  annotations and asserts pool wiring, not quality.
- Mark `_CONCEPT_EXPANSIONS` deprecated and bypass it when DB-backed expansion is available.

## What Is NOT in This Issue

- Any schema additions (all schema work is in Issues 170 and 171).
- Chunking, re-embedding, or ingestion changes.
- LLM-assisted extraction or reranker model changes.
- UI changes.
- Deletion of `_CONCEPT_EXPANSIONS` (scheduled for Issue 173 cleanup after no-regression gate).

## Architecture Decisions

- **Integration point is `_retrieve_hardened()`, not `retrieve_hybrid()`.** `retrieve_hybrid()`
  is a thin router; the `pools` dict is built and passed to `fuse_hardened_candidates()` inside
  `_retrieve_hardened()`. All new pools are inserted as named entries in `pools` before that
  call.
- **New pools are additive.** The existing dense + sparse + hybrid (RRF) pools continue to run.
  If the new pools produce zero candidates (missing annotations), retrieval degrades gracefully.
- **`corpus_expansion_terms` is a separate field, never merged into `concept_terms`.** See
  Part 1 below for rationale.
- **Structural recall tests are not quality tests.** See Part 3 for the explicit distinction.
- **Reranker enrichment is feature-flagged off by default.** `RAG_RERANKER_ENTITY_CONTEXT=1`
  prepends entity/concept labels to chunk text before Jina reranking. Default is 0.

---

## Part 1: Query Planner Changes

The only file changed in this part is `api/app/rag/retrieval.py` (plus `intent_router.py` if
`resolve_entity_ids` is better placed there). Read `retrieval.py` fully before editing.

### Entity alias normalization

Currently, `build_retrieval_query_plan()` calls `_extract_discussed_entities_for_plan()` which
returns raw surface strings like `["Amazon"]`. These are appended to `content_query` as text.

Add a normalization step immediately after that call:

```python
def resolve_entity_ids(
    surface_forms: list[str],
    db: Session,
) -> tuple[list[str], list[str]]:
    """
    Return (resolved_entity_ids, unresolved_surface_forms).

    Looks up each lowercased surface form in rag_entity_aliases WHERE is_active = TRUE.
    Unresolved forms fall back to the existing content_query text append (no behavior change).
    """
    if not surface_forms:
        return [], []
    rows = db.execute(
        text("""
            SELECT DISTINCT entity_id
            FROM rag_entity_aliases
            WHERE lower(alias) = ANY(:aliases)
              AND is_active = TRUE
        """),
        {"aliases": [s.lower() for s in surface_forms]},
    ).fetchall()
    resolved = [r.entity_id for r in rows]
    resolved_lower = {r.entity_id for r in rows}
    # surface forms with no alias match stay as unresolved
    unresolved = [
        s for s in surface_forms
        if s.lower() not in resolved_lower
           and s not in resolved_lower  # in case surface form == canonical id
    ]
    return resolved, unresolved
```

- Add `resolved_entity_ids: list[str]` to `RetrievalQueryPlan` (new field; dataclass is
  frozen so add via `field(default_factory=list)`).
- Add `resolved_entity_ids` to `RetrievalQueryPlan.as_dict()` output. Backwards-compatible.
- If the alias table is empty or the DB is unavailable, `resolved_entity_ids` stays `[]` and
  the unresolved surface form continues to be appended to `content_query` as before.

### Corpus-local expansion terms

After resolving entity IDs, fetch expansion terms from `rag_corpus_expansions`:

```python
def fetch_expansion_terms(
    author_ids: list[str],
    entity_ids: list[str],
    concept_ids: list[str],
    db: Session,
    *,
    max_terms: int = 15,
) -> list[str]:
    """
    Return the top expansion terms from rag_corpus_expansions for the given
    (author, entity/concept) pairs, sorted by npmi descending.
    Returns [] if DB unavailable or no rows found (graceful fallback).
    """
```

**Critical separation: `corpus_expansion_terms` must NOT be merged into `concept_terms`.**

- `concept_terms` = user-intent concepts extracted from the query.
- `corpus_expansion_terms` = corpus associations derived from annotations + NPMI.
- Merging would inflate `concept_term_hits` diagnostics and make it impossible to distinguish
  "the query contained this concept" from "the corpus associates this entity with this phrase".

Wire it up:
- Call `fetch_expansion_terms(author_ids, resolved_entity_ids, resolved_concept_ids, db)`
  inside `build_retrieval_query_plan()` after `resolve_entity_ids()`.
- Add `corpus_expansion_terms: list[str]` to `RetrievalQueryPlan`
  (`field(default_factory=list)`).
- Add `corpus_expansion_terms` to `RetrievalQueryPlan.as_dict()`.
- Fallback: if `corpus_expansion_terms` is empty, check `_CONCEPT_EXPANSIONS` dict as before.
  Mark the dict with a deprecation comment:
  ```python
  # DEPRECATED: replaced by rag_corpus_expansions (Issue 171). Remove in Issue 173.
  ```

---

## Part 2: Candidate Pool Functions

Add three new retrieval functions in `retrieval.py`. Read the existing `retrieve_keyword_chunks`
and `retrieve_similar_chunks` signatures before writing these — they must return the same
`list[RetrievedChunk]` type and use the same `corpus_class` tagging pattern.

### `retrieve_by_entity_ids`

```python
def retrieve_by_entity_ids(
    entity_ids: list[str],
    db: Session,
    *,
    author_ids: Optional[list[str]] = None,
    top_k: int = 30,
) -> list[RetrievedChunk]:
    """
    Return chunks annotated with any of the given entity_ids, ordered by
    annotation confidence descending.
    Scoped to author_ids when provided.
    Returns [] gracefully when entity_ids is empty or no annotated chunks exist.
    """
```

SQL core:
```sql
SELECT rc.id AS chunk_id,
       rc.text,
       rc.metadata_json,
       COALESCE(rd.author_id, rs.author_id) AS author_id,
       rce.confidence AS score
FROM rag_chunks rc
JOIN rag_chunk_entities rce ON rce.chunk_id = rc.id
JOIN rag_documents rd       ON rd.id = rc.document_id
JOIN rag_sources rs         ON rs.id = rd.source_id
WHERE rce.entity_id = ANY(:entity_ids)
  AND rce.is_active = TRUE
  [AND COALESCE(rd.author_id, rs.author_id) = ANY(:author_ids)]
ORDER BY rce.confidence DESC
LIMIT :top_k
```

Returned chunks carry `corpus_class='entity_annotation_pool'`. They enter RRF merge normally
and do NOT bypass deduplication, near-duplicate suppression, or the author gate.

### `retrieve_by_concept_ids`

```python
def retrieve_by_concept_ids(
    concept_ids: list[str],
    db: Session,
    *,
    author_ids: Optional[list[str]] = None,
    top_k: int = 30,
) -> list[RetrievedChunk]:
```

Same pattern as `retrieve_by_entity_ids`, joining `rag_chunk_concepts`.
Returned chunks carry `corpus_class='concept_annotation_pool'`.

---

## Part 3: Pool Integration into `_retrieve_hardened()`

**Read `_retrieve_hardened()` fully before editing.** The function is ~200 lines; the `pools`
dict is built incrementally starting at around line 2175, and `fuse_hardened_candidates()` is
called at around line 2326. The existing `topic_entity_pool` block is the template for how
pools are added.

Insert the three new pool blocks immediately after the `topic_entity_pool` block and before
`fuse_hardened_candidates()`:

```python
# --- Entity annotation pool (Issue 172) ---
if plan.resolved_entity_ids and retrieval_mode in {"hybrid", "sparse_only"}:
    pools["entity_annotation_pool"] = retrieve_by_entity_ids(
        plan.resolved_entity_ids,
        db,
        author_ids=effective_author_ids or (
            [effective_author_id] if effective_author_id else None
        ),
        top_k=fetch_k,
    )
    trace_retrieval_chunks(
        "pool_entity_annotation",
        str(plan.resolved_entity_ids),
        pools["entity_annotation_pool"],
    )

# --- Concept annotation pool (Issue 172) ---
if plan.resolved_concept_ids and retrieval_mode in {"hybrid", "sparse_only"}:
    pools["concept_annotation_pool"] = retrieve_by_concept_ids(
        plan.resolved_concept_ids,
        db,
        author_ids=effective_author_ids or (
            [effective_author_id] if effective_author_id else None
        ),
        top_k=fetch_k,
    )
    trace_retrieval_chunks(
        "pool_concept_annotation",
        str(plan.resolved_concept_ids),
        pools["concept_annotation_pool"],
    )

# --- Corpus expansion pool (Issue 172) ---
if plan.corpus_expansion_terms and retrieval_mode in {"hybrid", "sparse_only"}:
    expansion_query = " OR ".join(plan.corpus_expansion_terms[:15])
    pools["corpus_expansion_pool"] = retrieve_keyword_chunks(
        expansion_query,
        db,
        top_k=max(top_k, fetch_k // 2),
        hardening_enabled=True,
        **common_kwargs,
    )
    trace_retrieval_chunks(
        "pool_corpus_expansion",
        expansion_query,
        pools["corpus_expansion_pool"],
    )
```

All three pools pass through the existing `_HARDENED_MIN_CANDIDATE_POOL` accounting,
`_diversify_hardened_candidates`, near-duplicate suppression, and `_enforce_source_author_gate`.
No bypass of any hardening logic.

### Concept ID resolution at retrieval time

`plan.resolved_concept_ids` is populated by looking up `required_phrases` (from the plan) in
`rag_concept_aliases WHERE is_active = TRUE`. Use the same `resolve_entity_ids` pattern:

```python
def resolve_concept_ids(
    phrases: list[str],
    db: Session,
) -> list[str]:
    """
    Look up each phrase in rag_concept_aliases WHERE is_active = TRUE.
    Returns list of matched concept_ids.
    """
```

Add `resolved_concept_ids: list[str]` to `RetrievalQueryPlan` (`field(default_factory=list)`).

### Reranker context enrichment (optional, feature-flagged)

When `RAG_RERANKER_ENTITY_CONTEXT=1` and a chunk has entity/concept annotations, prepend a
structured prefix to the passage text before passing to Jina:

```
[Entities: Amazon, Costco] [Concepts: scale_economies_shared, capital_allocation]
{original chunk text}
```

This is off by default (`RAG_RERANKER_ENTITY_CONTEXT=0`). Do not enable without first running
the no-regression eval gate.

---

## Part 4: Diagnostics

**No new files.** Extend two existing structures in `retrieval.py`.

Add to `RetrievalQueryPlan.diagnostics` (in `as_dict()` output):
```python
{
    "resolved_entity_ids": [...],      # new
    "resolved_concept_ids": [...],     # new
    "corpus_expansion_terms": [...],   # new
    "entity_pool_size": N,             # new
    "concept_pool_size": N,            # new
    "expansion_terms_used_in_pool": N, # new (count of terms fed to corpus_expansion_pool)
}
```

Add to per-chunk trace in `_trace_chunk_item()`:
- `"entity_pool_member": true/false` — was this chunk retrieved from `entity_annotation_pool`?
- `"concept_pool_member": true/false` — from `concept_annotation_pool`?

These enable the curl-level diagnostic:
```bash
curl "http://localhost:8000/rag/retrieve?query=...&debug=true" | jq '.diagnostics'
```

---

## Part 5: Structural Recall Eval Suite

**Important distinction: these are structural recall tests, not quality tests.**

They verify that the pools are correctly wired: an entity pool for `entity_id='amazon'`
retrieves chunks annotated `entity_id='amazon'`. The gold set IS the annotation set, so these
tests prove the JOIN works, not that the retrieved chunks are semantically best.

Do NOT interpret structural recall scores as retrieval quality metrics. The hand-labeled golden
set in `api/app/rag/eval/fixtures/` remains the quality benchmark. The no-regression gate runs
on that set, not on the structural recall set.

### `api/app/rag/eval/parametric.py` (new file)

```python
def generate_entity_structural_recall_tests(
    db: Session,
    *,
    min_chunks: int = 5,
) -> list[GoldenQuery]:
    """
    For each (author, entity) pair where annotation count >= min_chunks:
      - query: "What does {author_display_name} say about {entity_canonical_name}?"
      - gold_chunk_ids: all chunk_ids annotated with entity_id for this author.
    Mode: structural_recall. Not counted in quality eval.
    """

def generate_concept_structural_recall_tests(
    db: Session,
    *,
    min_chunks: int = 5,
) -> list[GoldenQuery]:
    """
    Same pattern for (author, concept) annotation pairs.
    """
```

Results must be reported under `mode='structural_recall'` — separate from the hand-labeled
quality eval results. They must NOT affect the no-regression gate thresholds.

### Required thresholds for structural recall tests

These are wiring assertions, not IR quality thresholds:
- `candidate_entity_pool_size >= 3` — verified via `diagnostics`, not via recall@K.
  Asserts the pool contributed candidates, not that they were ranked first.
- If this fails, the bug is in the JOIN, the `is_active` filter, or `resolved_entity_ids`
  being empty.

### Cross-author leakage (explicit structural test)

For every single-author query (resolved `source_author_ids` length == 1):
- Assert all returned chunks have `author_id == source_author_ids[0]`.
- This invariant was implied by Issue 145 but is now explicitly tested per registered author.

### CLI integration

Add `--mode structural_recall` to `api/app/rag/eval/cli.py`.

```
python -m app.rag.eval.cli --mode structural_recall
```

Output: total tests generated, pass/fail count, authors covered.

### No-regression gate (quality, unchanged)

Existing eval baselines must not drop:
- `mean_ndcg@10` delta >= -0.02
- `mean_recall@10` delta >= -0.02

Gate runs on the hand-labeled golden set only:
```
python -m app.rag.eval.cli --mode quality --baseline fixtures/baseline.json
```

---

## Example Target Behavior

Query: `What does Nick Sleep say about Amazon's business model?`

Query plan after Issue 172:
```json
{
  "source_author_ids": ["nick_sleep"],
  "topic_entities": ["Amazon"],
  "resolved_entity_ids": ["amazon"],
  "resolved_concept_ids": [],
  "corpus_expansion_terms": ["scale economies shared", "customer service", "lower prices", "reinvestment", "costco"],
  "content_query": "amazon business model",
  "sparse_query": "amazon OR \"business model\"",
  "diagnostics": {
    "entity_pool_size": 31,
    "concept_pool_size": 0,
    "expansion_terms_used_in_pool": 5,
    "strict_source_author_filter": true
  }
}
```

Candidate pools active in `_retrieve_hardened()`:
1. `dense_content` — embedding search on "amazon business model" (Nick Sleep corpus)
2. `sparse_content` — tsquery on main sparse query (Nick Sleep corpus)
3. `entity_annotation_pool` — 31 Nick Sleep chunks annotated `entity_id='amazon'`
4. `corpus_expansion_pool` — keyword search on expansion terms (Nick Sleep corpus)

All four → `fuse_hardened_candidates()` (RRF) → `_diversify_hardened_candidates()` →
`_enforce_source_author_gate()` → Jina reranker → top-5 evidence.

Final evidence: Nick Sleep chunks only. Buffett/Munger chunks blocked by author gate.

---

## Acceptance Criteria

- [ ] `build_retrieval_query_plan()` for a query containing "Amazon" returns a plan where
  `resolved_entity_ids` contains `"amazon"` when the alias table is populated.
- [ ] `build_retrieval_query_plan()` for a Nick Sleep + Amazon query returns
  `corpus_expansion_terms` containing at least one non-empty term when expansion rows exist.
- [ ] `corpus_expansion_terms` is NOT present in `concept_terms` (verified in unit test).
- [ ] `retrieve_by_entity_ids(["amazon"], db, author_ids=["nick_sleep"])` returns > 0 chunks
  when Nick Sleep has Amazon-annotated chunks in the DB.
- [ ] `_retrieve_hardened()` in `retrieval.py` contains three new pool blocks
  (`entity_annotation_pool`, `concept_annotation_pool`, `corpus_expansion_pool`) inserted
  before the call to `fuse_hardened_candidates()`.
- [ ] Pool names appear in the `pool_sizes` field of the `hardened_fused_final` trace for an
  Amazon query against Nick Sleep.
- [ ] `retrieve_hybrid()` with entity pool active returns `entity_pool_member=true` on at least
  one chunk in trace output for an Amazon query against Nick Sleep.
- [ ] `RAG_RERANKER_ENTITY_CONTEXT=0` (default) leaves reranker input unchanged; `=1` prepends
  entity/concept labels without breaking the reranker pipeline.
- [ ] `_CONCEPT_EXPANSIONS` in `retrieval.py` is marked with the deprecation comment and
  bypassed when `corpus_expansion_terms` is non-empty.
- [ ] Structural recall eval runs without error:
  `python -m app.rag.eval.cli --mode structural_recall` generates >= 10 test cases across
  >= 3 authors.
- [ ] All structural recall entity tests with >= 5 annotated chunks pass
  `candidate_entity_pool_size >= 3` (verified via diagnostics).
- [ ] Structural recall results are reported separately; they do NOT affect the no-regression
  gate on the hand-labeled golden set.
- [ ] No-regression gate on hand-labeled golden set: `mean_ndcg@10` and `mean_recall@10` do
  not drop more than 0.02 from the pre-172 baseline.
- [ ] Backend APIs remain OpenAPI-compatible. `RetrievalQueryPlan.as_dict()` gains new fields
  but does not remove existing fields.
- [ ] `make api-smoke` passes after deployment.

---

## Task Checklist

- [ ] Confirm Issues 170 and 171 preconditions are met (annotated chunks exist, expansion rows
  exist) before starting any implementation.
- [ ] Read `retrieval.py` in full before editing. Note existing variable names:
  `effective_author_id`, `effective_author_ids`, `common_kwargs`, `fetch_k`, `retrieval_mode`.
- [ ] Add `resolved_entity_ids`, `resolved_concept_ids`, `corpus_expansion_terms` fields to
  `RetrievalQueryPlan` (frozen dataclass — use `field(default_factory=list)`).
- [ ] Implement `resolve_entity_ids()` and `resolve_concept_ids()` in `retrieval.py`.
- [ ] Implement `fetch_expansion_terms()` in `retrieval.py`.
- [ ] Update `build_retrieval_query_plan()` to call alias normalization and expansion fetch.
- [ ] Implement `retrieve_by_entity_ids()` and `retrieve_by_concept_ids()` in `retrieval.py`.
- [ ] Insert three pool blocks into `_retrieve_hardened()` (after `topic_entity_pool`, before
  `fuse_hardened_candidates()`).
- [ ] Confirm pools appear in `pool_sizes` field of `hardened_fused_final` trace.
- [ ] Add `entity_pool_member` / `concept_pool_member` flags to `_trace_chunk_item()`.
- [ ] Add diagnostics fields to `RetrievalQueryPlan.as_dict()`.
- [ ] Add deprecation comment to `_CONCEPT_EXPANSIONS`; add bypass when
  `corpus_expansion_terms` is non-empty.
- [ ] Implement `api/app/rag/eval/parametric.py` with `generate_entity_structural_recall_tests`
  and `generate_concept_structural_recall_tests`.
- [ ] Add `--mode structural_recall` to `api/app/rag/eval/cli.py`.
- [ ] Write unit tests:
  - `resolve_entity_ids` returns correct IDs for known aliases; returns `([], [surface])` when
    alias is not in DB.
  - `fetch_expansion_terms` returns `[]` when `rag_corpus_expansions` is empty (graceful).
  - `corpus_expansion_terms` not present in `concept_terms` on the returned plan.
  - `retrieve_by_entity_ids` returns chunks with correct `corpus_class='entity_annotation_pool'`.
  - Cross-author leakage: `retrieve_by_entity_ids` with `author_ids=['nick_sleep']` returns
    no chunks with a different author.
  - `_retrieve_hardened()` trace output contains `entity_annotation_pool` key when
    `resolved_entity_ids` is non-empty.
  - `RAG_RERANKER_ENTITY_CONTEXT=0` does not prepend any prefix to chunk text.
- [ ] Run no-regression eval on hand-labeled golden set; verify gate passes.
- [ ] Run `--mode structural_recall`; verify >= 10 tests generated, >= 3 authors.

<!-- IMMUTABLE_PLAN_END -->

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->

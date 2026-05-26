# Issue 171: Corpus-local expansion index (NPMI compute pipeline)

> **Depends on**: Issue 170 (entity/concept metadata layer, schema, extraction, backfill).
> Issue 171 is blocked until Issue 170's migrations are applied and backfill has run.
>
> **Delivers data consumed by**: Issue 172 (retrieval wiring). Issue 172 is blocked until
> this issue's migration has run and `compute_corpus_expansions` has produced rows.

## Problem

After Issue 170, the database contains chunk-level entity and concept annotations. However,
there is no mechanism to derive *corpus-local* expansion terms from those annotations:

1. **`_CONCEPT_EXPANSIONS` in `retrieval.py` is hardcoded for "mental models" only.** There is
   no corpus-derived expansion: the system cannot discover that Nick Sleep, when writing about
   Amazon, consistently uses the phrases "scale economies shared", "lower prices", and "Costco".

2. **The existing `_CONCEPT_EXPANSIONS` dict is a dead-end.** It is a one-author-one-concept
   special case that does not generalize. It will not improve recall for any other author or
   any other entity/concept combination.

3. **No precomputed expansion index exists.** Without a precomputed table, the only alternative
   is per-query corpus statistics, which is too slow for interactive retrieval.

## Objective

Build a corpus-local expansion index: for every `(author, entity)` and `(author, concept)` pair
that has sufficient chunk coverage, compute NPMI co-occurrence statistics from the annotated
corpus and store the top expansion terms in a new `rag_corpus_expansions` table.

This is a **pure offline, data-layer deliverable**. It does not touch `retrieval.py`, does not
change any live query path, and does not affect any existing API behavior. Issue 172 will wire
this table into retrieval.

## What Is NOT in This Issue

- Any changes to `retrieval.py` or `intent_router.py`.
- Changes to `RetrievalQueryPlan` or any retrieval function.
- Candidate pool integration, eval suite, diagnostics. (All in Issue 172.)
- UI changes.
- Chunking or re-embedding changes.

## Architecture Decisions

- **NPMI, not raw frequency.** Raw co-occurrence frequency over-weights common words. Normalized
  PMI (NPMI) adjusts for baseline term frequency and produces stable scores across corpora of
  different sizes.
- **Precomputed, not per-query.** The index is rebuilt on demand via a management command and
  recomputed after large ingestion runs. The command is idempotent (UPSERT on PK).
- **N-gram candidates (1/2/3-gram).** Single-token extraction would decompose "scale economies
  shared" into three weak 1-gram signals. The algorithm explicitly generates 1-gram, 2-gram,
  and 3-gram candidates so that multi-word phrases are discovered as coherent units.
- **`_CONCEPT_EXPANSIONS` is deprecated but not removed here.** It stays as a fallback in
  `retrieval.py` until Issue 172 validates the DB-backed path on a no-regression eval run.

## Schema

Migration: `migrations/054_corpus_expansion_index.sql`

```sql
CREATE TABLE rag_corpus_expansions (
  author_id       TEXT NOT NULL REFERENCES rag_authors(id) ON DELETE CASCADE,
  pivot_type      TEXT NOT NULL CHECK (pivot_type IN ('entity','concept')),
  pivot_id        TEXT NOT NULL,  -- entity_id or concept_id depending on pivot_type
  expansion_term  TEXT NOT NULL,  -- lowercase normalized term or phrase
  expansion_type  TEXT NOT NULL CHECK (expansion_type IN ('entity','concept','phrase')),
  expansion_ref_id TEXT,          -- set when expansion_type is 'entity' or 'concept'
  support_count   INT  NOT NULL,
  npmi            REAL NOT NULL,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (author_id, pivot_type, pivot_id, expansion_term)
);
CREATE INDEX rag_corpus_expansions_author_pivot
  ON rag_corpus_expansions(author_id, pivot_type, pivot_id);
```

### PMI Algorithm

For each `(author_id, pivot_type, pivot_id)` triple:

1. Collect `pivot_chunks`: all `rag_chunks` for this author that have the pivot entity/concept
   annotated (via `rag_chunk_entities` or `rag_chunk_concepts`).
2. Collect `author_chunks`: all `rag_chunks` for this author.
3. Let `N = len(author_chunks)`.
4. Generate candidate terms `T` from chunk text. Use **n-gram extraction (1-gram, 2-gram, and
   3-gram)**, not single-token tokenization. This is required because the most valuable
   expansion terms are multi-word phrases ("scale economies shared", "customer service",
   "lower prices", "long-term reinvestment"). Single-token extraction would decompose these
   into uninformative fragments.
   - Tokenize each `chunk.text` using the existing `_normalize_content_query` normalizer.
   - Generate all 1-grams, 2-grams, and 3-grams from the token sequence.
   - Filter against `_FEEDBACK_STOPWORDS` at the n-gram level: discard any n-gram where
     every token is a stopword; keep n-grams that contain at least one non-stopword token.
   - Discard n-grams that are entirely made up of stopwords or punctuation.
5. For each candidate term `t` in `T`:
   - `n_t = count(author_chunks whose text contains t as an n-gram)`
   - `n_pivot = len(pivot_chunks)`
   - `n_joint = count(pivot_chunks whose text contains t as an n-gram)`
   - Skip if `n_joint < min_support` (default: 3).
   - `P_joint = n_joint / N`
   - `P_pivot = n_pivot / N`
   - `P_t = n_t / N`
   - `PMI = log(P_joint / (P_pivot * P_t))`
   - `NPMI = PMI / -log(P_joint)` (range: [-1, 1])
   - Keep if `npmi >= 0.10`.
6. Also expand using other entities/concepts that co-occur in `pivot_chunks`:
   - For each entity `e` in `rag_chunk_entities` where chunk is in `pivot_chunks`:
     count co-occurrences and compute NPMI. Keep if `n_joint >= 3` and `npmi >= 0.10`.
   - Store with `expansion_type='entity'` and `expansion_ref_id=e`.
   - Same for concepts.
7. Store top 30 expansion terms per pivot (by NPMI descending) into `rag_corpus_expansions`.

### Compute Command

`python -m app.scripts.compute_corpus_expansions`

| Flag | Default | Effect |
|---|---|---|
| `--author-id ID` | all | Limit computation to one author |
| `--min-support N` | 3 | Minimum co-occurrence count |
| `--min-npmi F` | 0.10 | Minimum NPMI threshold |
| `--top-n N` | 30 | Max expansion terms per pivot |
| `--dry-run` | off | Print counts without writing |

Output:
```
[expansion] author=nick_sleep  entity=amazon      pivot_chunks=47  expansion_terms=18
[expansion] author=charlie_munger  entity=amazon  pivot_chunks=12  expansion_terms=9
...
[expansion] DONE authors=8 pivots=143 terms_stored=2104
```

Recompute after major ingestion runs. Command is idempotent (UPSERT on PK).

## Acceptance Criteria

- [ ] `migrations/054_corpus_expansion_index.sql` applies cleanly on `make api-rebuild`.
- [ ] `python -m app.scripts.compute_corpus_expansions` completes on a live DB with >= 1 author
  and stores expansion rows for >= 1 `(author, entity)` pair where chunk support >= 3.
- [ ] Running with `--dry-run` prints per-author/entity summary without writing any rows.
- [ ] Running twice (idempotent check) produces identical row counts (UPSERT on PK, no duplicates).
- [ ] `--author-id nick_sleep` limits computation to that author only; no rows written for others.
- [ ] For a Nick Sleep + Amazon pair with >= 3 chunk co-occurrences, the stored expansion terms
  include at least one multi-word phrase (2-gram or 3-gram), confirming n-gram extraction works.
- [ ] No changes to `retrieval.py`, `intent_router.py`, or any live query path.
- [ ] `make api-smoke` passes (no regressions; this issue makes no retrieval changes).

## Task Checklist

- [ ] Confirm Issue 170 is merged and backfill has run (coverage query returns > 0 annotated
  chunks across at least 1 author).
- [ ] Write `migrations/054_corpus_expansion_index.sql`.
- [ ] Implement `api/app/scripts/compute_corpus_expansions.py` with full NPMI algorithm:
  - n-gram candidate extraction (1/2/3-gram) using `_normalize_content_query` tokenizer
  - stopword filtering at n-gram level (discard if all tokens are stopwords)
  - NPMI math: P_joint, P_pivot, P_t, PMI, NPMI normalization
  - entity/concept co-expansion step (expansion_type='entity'/'concept')
  - UPSERT into `rag_corpus_expansions` via savepoints (per-pivot isolation)
  - CLI flags: `--author-id`, `--min-support`, `--min-npmi`, `--top-n`, `--dry-run`
- [ ] Write unit tests:
  - n-gram extraction produces 2-gram and 3-gram candidates (not only 1-grams)
  - n-gram filtered correctly when all tokens are stopwords
  - NPMI computation is numerically correct (known P values → known NPMI)
  - `--dry-run` writes no rows to DB
  - command is idempotent (run twice, same row count)
  - graceful skip when an author has zero annotated chunks
- [ ] Run `compute_corpus_expansions` against live DB; confirm rows exist in
  `rag_corpus_expansions` for >= 1 author.
- [ ] Verify multi-word phrase stored (SELECT from `rag_corpus_expansions` where
  `expansion_term LIKE '% %'` returns >= 1 row).


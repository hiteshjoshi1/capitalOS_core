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

<!-- IMMUTABLE_PLAN_END -->

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-171-entity-concept-retrieval-integration-and-corpus-expansion`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: migrations/054_corpus_expansion_index.sql applies cleanly
- Acceptance criterion: compute_corpus_expansions completes on live DB with >= 1 author and stores rows for >= 1 (author, entity) pair
- Acceptance criterion: --dry-run prints per-author/entity summary without writing rows
- Acceptance criterion: Running twice produces identical row counts (idempotency via UPSERT)
- Acceptance criterion: --author-id nick_sleep limits to that author only
- Acceptance criterion: Nick Sleep + Amazon pair stores multi-word phrase (2-gram or 3-gram) expansion terms
- Acceptance criterion: No changes to retrieval.py, intent_router.py, or any live query path
- Acceptance criterion: make api-smoke passes

## Prepare
Checked out `feature/issue-171-entity-concept-retrieval-integration-and-corpus-expansion` from `main` and ensured task file exists.

## Plan Summary
1) Write migration 054_corpus_expansion_index.sql with rag_corpus_expansions table and index. 2) Implement compute_corpus_expansions.py with n-gram extraction, NPMI math, entity/concept co-expansion, idempotent UPSERT, CLI flags. 3) Write unit tests for pure functions (tokenize, ngrams, NPMI) and mock-based DB tests (dry-run, skip). 4) Apply migration, run script, verify idempotency and multi-word phrase output. 5) Run full verification suite.

### Architecture Decisions
- NPMI precomputed offline: avoids per-query corpus statistics cost
- N-gram candidates (1/2/3-gram) using _normalize_content_query tokenizer to discover multi-word phrases like 'scale economies shared'
- Stopword filtering at n-gram level: discard n-grams where ALL tokens are in _FEEDBACK_STOPWORDS
- Deterministic ordering: sort pivot_ngrams_union and entity/concept dict keys before processing; sort tied NPMI values by expansion_term alpha to ensure idempotent top-N selection across Python runs
- UPSERT on PK (author_id, pivot_type, pivot_id, expansion_term) with per-pivot savepoints for failure isolation
- Entity and concept co-expansion step stores expansion_type='entity'/'concept' with expansion_ref_id set
- No changes to retrieval.py or any live query path — pure offline data layer

### Acceptance Criteria
- migrations/054_corpus_expansion_index.sql applies cleanly
- compute_corpus_expansions completes on live DB with >= 1 author and stores rows for >= 1 (author, entity) pair
- --dry-run prints per-author/entity summary without writing rows
- Running twice produces identical row counts (idempotency via UPSERT)
- --author-id nick_sleep limits to that author only
- Nick Sleep + Amazon pair stores multi-word phrase (2-gram or 3-gram) expansion terms
- No changes to retrieval.py, intent_router.py, or any live query path
- make api-smoke passes

### Planned Paths
- `migrations/054_corpus_expansion_index.sql`
- `api/app/scripts/compute_corpus_expansions.py`
- `api/tests/test_compute_corpus_expansions.py`

## Build Summary
Implemented Issue 171: corpus-local NPMI expansion index. Created migration 054_corpus_expansion_index.sql, implemented compute_corpus_expansions.py with full NPMI algorithm (1/2/3-gram extraction, stopword filtering, entity/concept co-expansion, idempotent UPSERT), and unit tests. Migration applied cleanly. Script ran against live DB producing 587 rows for nick_sleep including 216 multi-word phrases. All verification suites pass (825 backend tests, 189 frontend tests, 191 orch tests).

### Changed Files
- `api/app/scripts/compute_corpus_expansions.py`
- `api/tests/test_compute_corpus_expansions.py`
- `migrations/054_corpus_expansion_index.sql`
- `tasks/issue-171-entity-concept-retrieval-integration-and-corpus-expansion.md`

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
Implemented Issue 171: corpus-local NPMI expansion index. Created migration 054_corpus_expansion_index.sql, implemented compute_corpus_expansions.py with full NPMI algorithm (1/2/3-gram extraction, stopword filtering, entity/concept co-expansion, idempotent UPSERT), and unit tests. Migration applied cleanly. Script ran against live DB producing 587 rows for nick_sleep including 216 multi-word phrases. All verification suites pass (825 backend tests, 189 frontend tests, 191 orch tests).

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` migrations/054_corpus_expansion_index.sql applies cleanly on make api-rebuild: make db-migrate output: '054_corpus_expansion_index.sql' → CREATE TABLE, CREATE INDEX
- `pass` compute_corpus_expansions completes on live DB with >= 1 author and stores expansion rows for >= 1 (author, entity) pair where chunk support >= 3: DONE authors=1 pivots=25 terms_stored=587; nick_sleep + amazon has 33 pivot_chunks, 30 expansion terms
- `pass` Running with --dry-run prints per-author/entity summary without writing any rows: Dry-run output showed per-pivot lines and DONE; DB row count unchanged after dry-run. Unit test TestRunComputeDryRun confirms no commit/insert calls
- `pass` Running twice (idempotent check) produces identical row counts: count1=587, run2 terms_stored=587, count2=587 — deterministic sort ensures identical top-N selection
- `pass` --author-id nick_sleep limits computation to that author only; no rows written for others: SELECT DISTINCT author_id FROM rag_corpus_expansions returns only 'nick_sleep'
- `pass` Nick Sleep + Amazon pair stores >= 1 multi-word phrase (2-gram or 3-gram): SELECT expansion_term LIKE '% %' WHERE pivot_id='amazon': 'scale efficiencies shared', 'jeff bezos', 'nebraska furniture mart', etc. Total 216 multi-word phrases for nick_sleep
- `pass` No changes to retrieval.py, intent_router.py, or any live query path: git diff shows only 3 new files: migration, script, tests. No modifications to existing files except task markdown
- `pass` make api-smoke passes (no regressions): Health OK, dashboard summary returned valid JSON with status 200

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-171-entity-concept-retrieval-integration-and-corpus-expansion`.
<!-- MACHINE_RENDERED_END -->

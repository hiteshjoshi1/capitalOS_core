# Issue 170: Entity and concept metadata layer for RAG

> **Scope**: Data layer only — schema, seed registries, deterministic extraction, and backfill.
> Retrieval integration, corpus-local expansion, query planner changes, and eval are Issue 171.

## Problem

The retrieval pipeline extracts topic entities like "Amazon" from queries at query-time using
regex (`_CAPITALIZED_ENTITY_RE` in `intent_router.py`), but these surface strings are never
normalized to canonical IDs and are never stored against chunks. Concretely:

1. **No entity pool exists in retrieval.** Entities only enrich the `content_query` string. There
   is no separate DB JOIN that retrieves all Nick Sleep chunks explicitly mentioning Amazon.
2. **Concept expansion is static and hardcoded.** `_CONCEPT_EXPANSIONS` in `retrieval.py` covers
   "mental models" only. It cannot adapt to what a given author actually associates with a concept.
3. **No chunk-level annotations.** You cannot ask "how many Buffett chunks mention Coca-Cola"
   without a full-text search that degrades on paraphrases and author-specific terminology.
4. **Alias normalization does not exist.** "Amazon", "AMZN", and "Amazon.com" are different
   strings. They do not drive the same candidate pool.

Before retrieval can use entity/concept metadata, that metadata must exist in the database.
This issue builds the data layer.

## Objective

- Add Postgres tables for entities, entity aliases, concepts, and concept aliases.
- Add a curated seed registry covering ~35 investment-writing entities (~25 companies + ~8 persons) and ~50 concepts.
- Implement deterministic, alias-driven chunk-level extraction that runs during ingestion
  and via an idempotent backfill command.
- Track extraction coverage per chunk in `metadata_json` so completeness can be queried.

## What Is NOT in This Issue

- Corpus-local expansion index computation → Issue 171.
- Query planner changes to use canonical entity IDs → Issue 171.
- Entity/concept candidate pools in retrieval → Issue 171.
- Generated eval/invariant tests → Issue 171.
- LLM-assisted entity extraction. Extraction is deterministic alias matching only.
- Any changes to chunking, parsing, or the embedding pipeline.

## Architecture Decisions

- **Postgres only.** No external graph database.
- **Alias-driven extraction.** Extraction finds entities and concepts only if they match the
  curated alias registry. It does not auto-register new entities from surface forms. This keeps
  extraction deterministic and the alias uniqueness constraint enforceable.
- **Non-destructive ingestion hook.** Extraction failure must not prevent chunk persistence.
  The ingestion pipeline wraps the extraction call in try/except. Failures are logged at
  WARNING level; the ingestion job continues and completes normally.
- **Idempotent with registry versioning.** Both the ingestion hook and the backfill command
  write `extraction_attempted: true`, `entity_concept_extractor_version: "v1"`,
  `entity_concept_registry_version: "<YYYY-MM-DD of seed migration>"`, and
  `entity_concept_extracted_at: "<iso8601>"` into `chunk.metadata_json`. Re-running skips
  chunks whose stored `entity_concept_extractor_version` and `entity_concept_registry_version`
  match the current values, unless `--force` is passed. When the alias registry is updated
  (new entities or aliases added), bump `entity_concept_registry_version`; the backfill command
  re-extracts only stale chunks without needing `--force`. This prevents the permanent skip
  problem: a chunk annotated with v1/2026-05-26 will be re-processed when the registry version
  changes to 2026-06-01.
- **No Python dict replacement yet.** `_KNOWN_CONCEPT_PHRASES`, `_CONCEPT_EXPANSIONS`, and
  `_KNOWN_AUTHORS` in `retrieval.py` / `intent_router.py` are NOT changed in this issue.
  Issue 171 will migrate callers to DB-backed registries once this layer is validated.
- **Extraction is chunk-scoped.** The unit of annotation is one chunk, not a document. This
  keeps extraction fast and allows partial backfills without re-chunking.

## Extraction Algorithm

Three phases applied in order to `chunk.text`:

**Phase 1 — Entity alias scan:**
- Load all active (`is_active=true`) `rag_entity_aliases` rows into a lowercase dict: `alias -> entity_id`.
- For each alias, compile a regex pattern at startup (not per-chunk) using **custom boundary rules**:
  - Standard aliases: wrap with `(?<![\w.])` and `(?![\w.])` (neither preceded nor followed by a
    word character or dot). This correctly handles aliases embedded in prose without matching
    partial substrings.
  - Aliases containing special characters (`.`, `/`, `'`, `-`) such as `brk.b`, `amazon.com`,
    `see's`, `p/e ratio`, `moody's`: use `re.escape()` on the alias and wrap with
    `(?<![\w])` / `(?![\w])` lookarounds applied to the non-special-char boundary only.
    Example: `re.escape("brk.b")` → `brk\.b` → pattern `(?<![\w])brk\.b(?![\w])`.
  - Short tickers (`alias_type='ticker'` AND `len(alias) <= 2`): require the alias to be
    surrounded by non-alphanumeric chars on both sides, e.g. `(?<![A-Za-z0-9])KO(?![A-Za-z0-9])`.
    This prevents `"F"` (Ford ticker) from matching inside words. If no safe boundary is found,
    skip the alias for this chunk.
- Scan `chunk.text` (lowercased copy) using the pre-compiled patterns.
- For each hit: upsert `rag_chunk_entities` with `extractor='alias_registry'`, `confidence=1.0`.
- Multiple aliases of the same entity in one chunk collapse to one row (PK is `(chunk_id, entity_id)`).

**Phase 2 — Capitalized surface form matching:**
- Apply `_CAPITALIZED_ENTITY_RE` (already in `retrieval.py`) to `chunk.text` to find capitalized
  multi-word spans.
- Lowercase each span and look it up in the alias dict (active aliases only).
- If found: upsert `rag_chunk_entities` with `extractor='surface_form'`, `confidence=0.8`.
- If not found in the alias table: discard. Do not auto-register new entities.

**Phase 3 — Concept alias scan:**
- Load all active (`is_active=true`) `rag_concept_aliases` rows into a lowercase dict: `alias -> concept_id`.
- For each alias, compile a regex using the same custom boundary rules as Phase 1
  (re.escape + lookarounds). This correctly handles multi-word phrases like
  `"scale economies shared"` (must not match inside a longer phrase), `"p/e ratio"` (slash),
  and `"mr. market"` (dot).
- Scan `chunk.text` (lowercased) using the pre-compiled patterns.
- For each hit: upsert `rag_chunk_concepts` with `extractor='concept_alias_registry'`, `confidence=1.0`.

After all three phases, update `chunk.metadata_json`:
```json
{
  "extraction_attempted": true,
  "entities_extracted_count": 3,
  "concepts_extracted_count": 2
}
```

## Schema

Migration: `migrations/052_entity_concept_metadata.sql`

```sql
-- Canonical entity registry
CREATE TABLE rag_entities (
  id             TEXT        PRIMARY KEY,  -- slug: 'amazon', 'berkshire_hathaway'
  entity_type    TEXT        NOT NULL CHECK (entity_type IN ('company','person','author','ticker','other')),
  canonical_name TEXT        NOT NULL,
  metadata_json  JSONB       NOT NULL DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Alias -> entity mapping. One alias belongs to exactly one entity.
CREATE TABLE rag_entity_aliases (
  entity_id  TEXT    NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
  alias      TEXT    NOT NULL,  -- lowercase normalized
  alias_type TEXT    NOT NULL CHECK (alias_type IN ('name','ticker','short_name','surface_form')),
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,  -- set false to soft-disable ambiguous aliases
  PRIMARY KEY (entity_id, alias)
);
-- UNIQUE on alias only where is_active=TRUE. Inactive aliases can coexist without uniqueness enforcement
-- because they will never be loaded into the extraction dict.
CREATE UNIQUE INDEX rag_entity_aliases_alias_uniq ON rag_entity_aliases(alias) WHERE is_active = TRUE;
CREATE INDEX        rag_entity_aliases_entity_id  ON rag_entity_aliases(entity_id);

-- Chunk <-> entity annotations
CREATE TABLE rag_chunk_entities (
  chunk_id     UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
  entity_id    TEXT NOT NULL REFERENCES rag_entities(id) ON DELETE CASCADE,
  surface_text TEXT,
  confidence   REAL NOT NULL DEFAULT 1.0,
  extractor    TEXT NOT NULL,
  PRIMARY KEY (chunk_id, entity_id)
);
CREATE INDEX rag_chunk_entities_entity_id ON rag_chunk_entities(entity_id);
CREATE INDEX rag_chunk_entities_chunk_id  ON rag_chunk_entities(chunk_id);

-- Canonical concept registry
CREATE TABLE rag_concepts (
  id             TEXT PRIMARY KEY,  -- slug: 'mental_models', 'margin_of_safety'
  canonical_name TEXT NOT NULL,
  domain         TEXT,              -- 'investing','psychology','valuation','operations','macro'
  description    TEXT,
  metadata_json  JSONB NOT NULL DEFAULT '{}'
);

-- Alias -> concept mapping. One alias belongs to exactly one concept.
CREATE TABLE rag_concept_aliases (
  concept_id TEXT    NOT NULL REFERENCES rag_concepts(id) ON DELETE CASCADE,
  alias      TEXT    NOT NULL,  -- lowercase normalized
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (concept_id, alias)
);
CREATE UNIQUE INDEX rag_concept_aliases_alias_uniq ON rag_concept_aliases(alias) WHERE is_active = TRUE;
CREATE INDEX        rag_concept_aliases_concept_id ON rag_concept_aliases(concept_id);

-- Chunk <-> concept annotations
CREATE TABLE rag_chunk_concepts (
  chunk_id    UUID NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
  concept_id  TEXT NOT NULL REFERENCES rag_concepts(id) ON DELETE CASCADE,
  surface_text TEXT,
  confidence  REAL NOT NULL DEFAULT 1.0,
  extractor   TEXT NOT NULL,
  PRIMARY KEY (chunk_id, concept_id)
);
CREATE INDEX rag_chunk_concepts_concept_id ON rag_chunk_concepts(concept_id);
CREATE INDEX rag_chunk_concepts_chunk_id   ON rag_chunk_concepts(chunk_id);
```

**Critical notes:**
- The partial `UNIQUE INDEX` on `alias WHERE is_active = TRUE` enforces that one active surface
  form maps to exactly one entity/concept. Ambiguous aliases are inserted with `is_active=FALSE`
  so they are excluded from extraction without being silently deleted. This makes editorial
  decisions recoverable and auditable.
- Extraction loads only `WHERE is_active = TRUE` aliases. Inactive aliases are documented in
  the seed migration SQL with a comment explaining why they are excluded.
- `rag_chunk_entities` PK is `(chunk_id, entity_id)` so extraction upserts are safe to replay.
- `rag_corpus_expansions` is NOT in this migration — that is Issue 171.

## Seed Registry

Migration: `migrations/053_seed_entity_concept_registry.sql`

Use `INSERT INTO ... ON CONFLICT DO NOTHING` so this migration is re-runnable.

### Entities

Authors are already in `rag_authors`. Do **not** duplicate them in `rag_entities`.
Author alias resolution at query time is handled by the existing `_KNOWN_AUTHORS` dict
and will be migrated to a DB lookup in Issue 171.

**Companies (entity_type = 'company')** — minimum viable set:

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `amazon` | Amazon | `amazon`, `amazon.com`, `amzn` |
| `berkshire_hathaway` | Berkshire Hathaway | `berkshire hathaway`, `berkshire`, `brk`, `brk.a`, `brk.b`, `brk-b` |
| `apple` | Apple | `apple`, `apple inc`, `aapl` |
| `alphabet` | Alphabet / Google | `alphabet`, `google`, `googl`, `goog` |
| `microsoft` | Microsoft | `microsoft`, `msft` |
| `costco` | Costco | `costco`, `costco wholesale`, `cost` |
| `coca_cola` | Coca-Cola | `coca-cola`, `coca cola`, `coke` |
| `wells_fargo` | Wells Fargo | `wells fargo`, `wfc` |
| `byd` | BYD | `byd`, `byd company` |
| `walmart` | Walmart | `walmart`, `wal-mart`, `wmt` |
| `meta` | Meta / Facebook | `meta`, `facebook` |
| `netflix` | Netflix | `netflix`, `nflx` |
| `tesla` | Tesla | `tesla`, `tsla` |
| `samsung` | Samsung | `samsung` |
| `alibaba` | Alibaba | `alibaba`, `baba` |
| `toyota` | Toyota | `toyota` |
| `visa` | Visa | `visa` |
| `jpmorgan` | JPMorgan Chase | `jpmorgan`, `jpmorgan chase`, `jpm` |
| `american_express` | American Express | `american express`, `amex` |
| `moodys` | Moody's | `moodys`, `moody's` |
| `sees_candies` | See's Candies | `see's candies`, `sees candies`, `sees` |
| `geico` | GEICO | `geico` |
| `wesco` | Wesco Financial | `wesco`, `wesco financial` |
| `djco` | Daily Journal Corporation | `daily journal`, `djco` |
| `ford_motor` | Ford Motor Company | `ford motor`, `ford motor company` |

**People — non-author persons (entity_type = 'person')**:

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `jeff_bezos` | Jeff Bezos | `jeff bezos`, `bezos` |
| `elon_musk` | Elon Musk | `elon musk`, `musk` |
| `bill_gates` | Bill Gates | `bill gates`, `gates` |
| `henry_ford` | Henry Ford | `henry ford`, `ford` |
| `sam_walton` | Sam Walton | `sam walton`, `walton` |
| `john_d_rockefeller` | John D. Rockefeller | `john d. rockefeller`, `rockefeller` |
| `adam_smith` | Adam Smith | `adam smith` |
| `ben_franklin` | Benjamin Franklin | `benjamin franklin`, `ben franklin` |

### Concepts

**Domain: valuation**

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `intrinsic_value` | Intrinsic Value | `intrinsic value`, `intrinsic worth` |
| `margin_of_safety` | Margin of Safety | `margin of safety` |
| `owner_earnings` | Owner Earnings | `owner earnings` |
| `dcf` | Discounted Cash Flow | `dcf`, `discounted cash flow` |
| `price_to_earnings` | Price-to-Earnings | `p/e ratio`, `price-to-earnings`, `price to earnings` |
| `book_value` | Book Value | `book value`, `price-to-book`, `p/b ratio` |

**Domain: investing**

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `moat` | Economic Moat | `moat`, `economic moat`, `durable competitive advantage` |
| `circle_of_competence` | Circle of Competence | `circle of competence` |
| `capital_allocation` | Capital Allocation | `capital allocation` |
| `reinvestment` | Reinvestment | `reinvestment`, `reinvest`, `reinvesting` |
| `pricing_power` | Pricing Power | `pricing power` |
| `competitive_advantage` | Competitive Advantage | `competitive advantage`, `sustainable advantage` |
| `long_termism` | Long-Termism | `long-termism`, `long-term thinking`, `long-term orientation` |
| `checklist` | Investing Checklist | `checklist` |
| `opportunity_cost` | Opportunity Cost | `opportunity cost` |
| `position_sizing` | Position Sizing | `position sizing`, `portfolio concentration` |
| `scale_economies_shared` | Scale Economies Shared | `scale economies shared`, `scale economies` |
| `customer_obsession` | Customer Obsession | `customer obsession`, `customer focus` |
| `flywheel` | Flywheel Effect | `flywheel`, `flywheel effect`, `virtuous cycle` |
| `network_effects` | Network Effects | `network effects`, `network effect` |
| `switching_costs` | Switching Costs | `switching costs`, `switching cost`, `lock-in` |
| `insurance_float` | Insurance Float | `float`, `insurance float` |
| `share_buybacks` | Share Buybacks | `share buybacks`, `buyback`, `share repurchase` |

**Domain: psychology**

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `mental_models` | Mental Models | `mental models`, `mental model`, `latticework` |
| `inversion` | Inversion | `inversion`, `invert`, `thinking backwards` |
| `incentives` | Incentives | `incentives`, `incentive-caused bias`, `incentive superresponse` |
| `social_proof` | Social Proof | `social proof` |
| `loss_aversion` | Loss Aversion | `loss aversion` |
| `authority_bias` | Authority Bias | `authority bias` |
| `availability_bias` | Availability Bias | `availability bias`, `availability heuristic` |
| `lollapalooza` | Lollapalooza Effect | `lollapalooza`, `lollapalooza effect` |
| `temperament` | Investor Temperament | `temperament`, `investor temperament` |
| `mr_market` | Mr. Market | `mr. market`, `mr market` |

**Domain: operations**

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `management_quality` | Management Quality | `management quality`, `management integrity` |
| `corporate_culture` | Corporate Culture | `corporate culture`, `company culture` |
| `owner_operator` | Owner-Operator | `owner-operator`, `owner operator`, `owner-managed` |

**Domain: macro**

| id | canonical_name | aliases (lowercase) |
|---|---|---|
| `inflation` | Inflation | `inflation`, `inflationary` |
| `interest_rates` | Interest Rates | `interest rates`, `interest rate` |
| `second_level_thinking` | Second-Level Thinking | `second level thinking`, `second-level thinking` |

### Alias Collision Policy

The partial UNIQUE index (active aliases only) enforces that no two active aliases collide.
Ambiguous aliases must be inserted with `is_active=FALSE` and a SQL comment explaining why.
This keeps the decision visible and reversible. Do NOT silently omit ambiguous aliases.

**Documented ambiguous aliases (insert as inactive with comment):**

| alias | ambiguity reason | resolution |
|---|---|---|
| `ford` | Henry Ford (person) vs Ford Motor Company | active on `henry_ford`; Ford Motor uses `ford motor` only |
| `float` | generic word vs insurance float | active on `insurance_float`; generic use excluded |
| `apple` | company vs common noun (fruit) | active on `apple` for the company; low false-positive risk in investment prose |
| `meta` | Meta/Facebook vs generic adjective | inserted `is_active=FALSE` on `meta` entity; use `facebook` or `meta platforms` instead until corpus evidence confirms safe |
| `cost` | Costco ticker vs generic word | inserted `is_active=FALSE`; use `costco` alias instead |
| `gates` | Bill Gates vs generic word | active on `bill_gates`; low false-positive risk in investment prose |
| `musk` | Elon Musk vs generic word | active on `elon_musk`; low false-positive risk |

**Short ticker policy:**
Single and two-character tickers (`v`, `ko`, `f`, `ge`, `fb`) are inserted as
`is_active=FALSE` in the initial seed. They can be activated in a follow-up migration
once a tighter boundary pattern (non-alphanumeric on both sides) is validated against
a sample corpus.

## Backfill Command

`python -m app.scripts.backfill_entity_concepts`

| Flag | Default | Effect |
|---|---|---|
| `--dry-run` | off | Print counts; do not write |
| `--author-id ID` | all | Limit to one author's chunks |
| `--batch-size N` | 200 | Chunks per transaction |
| `--force` | off | Reprocess chunks already marked `extraction_attempted` |

Behavior:
- For each `rag_chunk` where `metadata_json->>'extraction_attempted'` is missing or not `'true'`,
  OR where `entity_concept_registry_version` does not match the current registry version
  (unless `--force` is also off and versions match), run the three-phase extraction.
- Batch processing with **per-chunk failure isolation using database savepoints**:
  - Fetch `--batch-size` chunks per iteration.
  - For each chunk in the batch: `SAVEPOINT sp_chunk_{id}` → run extraction → on success
    `RELEASE SAVEPOINT sp_chunk_{id}` → on failure `ROLLBACK TO SAVEPOINT sp_chunk_{id}`,
    log the error with chunk_id and continue to the next chunk.
  - Commit the batch after processing all chunks (successful + failed).
  - A single chunk failure does not roll back successfully processed chunks in the same batch.
- Output (one line per batch):

```
[backfill] batch=1  processed=200 entities=412 concepts=187 skipped=0  failed=0
[backfill] batch=2  processed=200 entities=389 concepts=201 skipped=0  failed=2
...
[backfill] DONE total_chunks=2400 total_entities=9823 total_concepts=4201 skipped=0 failed=3
```

Idempotency guarantee: Running the command twice without `--force` produces identical DB
state and outputs `skipped=N` equal to the previously processed count.

## Ingestion Integration

After `_persist_chunks()` in `api/app/rag/ingestion/pipeline.py`, call:
`extract_and_store_chunk_annotations(chunk_id, chunk_text, db)`

This is a new function in `api/app/rag/ingestion/entity_extractor.py`.

Rules:
- Wrapped in `try/except Exception`. Exceptions log at `WARNING` and do not propagate.
- Chunks are persisted regardless of extraction outcome.
- The ingestion job output includes `entities_extracted` and `concepts_extracted` totals
  per document.

## Chunk Metadata Quality Tracking

The following fields are written into `rag_chunks.metadata_json` by both the ingestion hook
and the backfill command:

| Field | Type | Meaning |
|---|---|---|
| `extraction_attempted` | bool | Was extraction run on this chunk? |
| `entities_extracted_count` | int | Distinct entity annotations found |
| `concepts_extracted_count` | int | Distinct concept annotations found |
| `entity_concept_extractor_version` | str | Extractor code version (e.g. `"v1"`) |
| `entity_concept_registry_version` | str | Registry snapshot date (e.g. `"2026-05-26"`) |
| `entity_concept_extracted_at` | str | ISO-8601 timestamp of extraction run |

These fields enable coverage queries without joining annotation tables:

```sql
SELECT
  COUNT(*) FILTER (WHERE metadata_json->>'extraction_attempted' = 'true') AS annotated,
  COUNT(*) FILTER (WHERE metadata_json->>'extraction_attempted' IS DISTINCT FROM 'true') AS unannotated,
  AVG((metadata_json->>'entities_extracted_count')::int)
    FILTER (WHERE metadata_json->>'extraction_attempted' = 'true') AS avg_entities_per_chunk
FROM rag_chunks;
```

## Example Target State

After this issue ships, these DB queries become possible — they are the queries Issue 171's
retrieval pools will run at query time:

```sql
-- How many Nick Sleep chunks mention Amazon?
SELECT count(*)
FROM rag_chunk_entities rce
JOIN rag_chunks rc    ON rc.id = rce.chunk_id
JOIN rag_documents rd ON rd.id = rc.document_id
WHERE rce.entity_id = 'amazon' AND rd.author_id = 'nick_sleep';

-- Top concepts in Munger's corpus by chunk coverage
SELECT rco.canonical_name, count(*) AS chunk_hits
FROM rag_chunk_concepts rcc
JOIN rag_concepts rco  ON rco.id = rcc.concept_id
JOIN rag_chunks rc     ON rc.id = rcc.chunk_id
JOIN rag_documents rd  ON rd.id = rc.document_id
WHERE rd.author_id = 'charlie_munger'
GROUP BY rco.canonical_name ORDER BY chunk_hits DESC LIMIT 10;
```

## Acceptance Criteria

- [ ] `migrations/052_entity_concept_metadata.sql` creates all six tables with correct keys and
  indexes. `make api-rebuild` and `make db-reset` complete without errors.
- [ ] `migrations/053_seed_entity_concept_registry.sql` seeds >= 25 companies, >= 8 persons
  (>= 33 entities total), and >= 50 concepts. Migration is idempotent (`ON CONFLICT DO NOTHING`).
- [ ] Ambiguous aliases listed in the collision policy table are present in the seed as
  `is_active=FALSE` rows with SQL comments explaining the exclusion decision.
- [ ] `SELECT alias, count(*) FROM rag_entity_aliases WHERE is_active = TRUE GROUP BY alias HAVING count(*) > 1`
  returns 0 rows (active alias uniqueness verified).
- [ ] Same active-alias uniqueness check passes for `rag_concept_aliases`.
- [ ] `python -m app.scripts.backfill_entity_concepts --dry-run` completes without error and
  prints a summary line.
- [ ] `python -m app.scripts.backfill_entity_concepts` on a DB with >= 500 chunks completes in
  under 60 seconds and sets `extraction_attempted=true` on every processed chunk.
- [ ] Running the backfill twice without `--force` outputs `skipped=N` equal to the first run's
  `processed=N` count; `rag_chunk_entities` and `rag_chunk_concepts` row counts do not change.
- [ ] Injecting a savepoint failure on one chunk in a 10-chunk test batch causes only that chunk
  to be counted as `failed=1`; the other 9 chunks are annotated successfully.
- [ ] After the seed migration is bumped to a new `entity_concept_registry_version`, running
  the backfill without `--force` re-processes all chunks with the stale version.
- [ ] Injecting a mock exception in `extract_and_store_chunk_annotations` does not prevent chunk
  persistence; ingestion completes and the chunk exists in `rag_chunks`.
- [ ] After ingesting a new source whose text contains "Amazon" or "Berkshire":
  `SELECT count(*) FROM rag_chunk_entities WHERE chunk_id IN (SELECT id FROM rag_chunks WHERE ...)
  AND entity_id IN ('amazon','berkshire_hathaway')` returns > 0.
- [ ] Unit tests cover: Phase 1 exact alias match, Phase 1 dot-containing alias (`brk.b`,
  `amazon.com`), Phase 1 apostrophe alias (`moody's`, `see's`), Phase 1 short-ticker boundary
  rule, Phase 2 surface form hit, Phase 2 miss (no row created), Phase 3 multi-word concept
  phrase match (`scale economies shared`), Phase 3 slash alias (`p/e ratio`), idempotent
  re-extraction (no duplicate rows), `--force` reprocessing, registry version bump triggers
  re-extraction of stale chunks, inactive alias is not matched.
- [ ] Backend APIs remain OpenAPI-compatible; no router changes.
- [ ] `make api-smoke` passes after deployment.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

- [ ] Write `migrations/052_entity_concept_metadata.sql`.
- [ ] Write `migrations/053_seed_entity_concept_registry.sql` with entity and concept seed data.
- [ ] Add SQLAlchemy ORM models for all six tables in `api/app/models/rag.py`.
- [ ] Implement `api/app/rag/ingestion/entity_extractor.py` with three-phase extraction pipeline.
- [ ] Integrate extraction hook into `api/app/rag/ingestion/pipeline.py` (try/except, non-fatal).
- [ ] Implement `api/app/scripts/backfill_entity_concepts.py` with all flags.
- [ ] Write unit tests in `api/tests/rag/test_entity_extractor.py`.
- [ ] Run `make api-rebuild`; verify migrations apply cleanly on a fresh DB.
- [ ] Run backfill against live DB; run coverage query; verify counts are non-zero.
- [ ] Confirm ingestion smoke test with mock extraction failure injected.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: Implemented the entity and concept metadata data layer for RAG (Issue 170). Created Postgres schema migrations, curated seed registries, deterministic alias-driven extraction pipeline, ingestion integration hook, backfill command, and unit tests. No router changes; all APIs remain OpenAPI-compatible.
- next_action: Inspect deterministic gate failures, apply mitigations, then rerun the workflow.
- pipeline_version: `v3`
- provider_model: `copilot/claude-sonnet-4.6`
- latest_failed_checks: `test-backend`
- retry_gate_pending: `no`
- retry_detail: `test-backend` stopped after attempt 1/3: Code failure with no auto-fix available: tests/test_dashboard.py:216: AssertionError
- blocked_reason: Deterministic gates failed: test-backend
- stopped_due_to: Verification remained red after the available automated recovery steps.

## Active Requirements
- Acceptance criterion: migrations/052_entity_concept_metadata.sql creates all six tables with correct keys and indexes; make api-rebuild and make db-reset complete without errors
- Acceptance criterion: migrations/053_seed_entity_concept_registry.sql seeds >= 25 companies, >= 8 persons (>= 33 entities total), and >= 50 concepts; migration is idempotent (ON CONFLICT DO NOTHING)
- Acceptance criterion: Ambiguous aliases listed in the collision policy table are present in the seed as is_active=FALSE rows with SQL comments explaining the exclusion decision
- Acceptance criterion: SELECT alias, count(*) FROM rag_entity_aliases WHERE is_active = TRUE GROUP BY alias HAVING count(*) > 1 returns 0 rows
- Acceptance criterion: Same active-alias uniqueness check passes for rag_concept_aliases
- Acceptance criterion: python -m app.scripts.backfill_entity_concepts --dry-run completes without error and prints a summary line
- Acceptance criterion: python -m app.scripts.backfill_entity_concepts on a DB with >= 500 chunks completes in under 60 seconds and sets extraction_attempted=true on every processed chunk
- Acceptance criterion: Running the backfill twice without --force outputs skipped=N equal to the first run's processed=N count; annotation table row counts do not change
- Acceptance criterion: Injecting a savepoint failure on one chunk in a 10-chunk test batch causes only that chunk to be counted as failed=1; the other 9 chunks are annotated successfully
- Acceptance criterion: After the seed migration is bumped to a new entity_concept_registry_version, running the backfill without --force re-processes all chunks with the stale version
- Acceptance criterion: Injecting a mock exception in extract_and_store_chunk_annotations does not prevent chunk persistence; ingestion completes and the chunk exists in rag_chunks
- Acceptance criterion: After ingesting a new source whose text contains Amazon or Berkshire: SELECT count(*) FROM rag_chunk_entities WHERE entity_id IN ('amazon','berkshire_hathaway') returns > 0
- Acceptance criterion: Unit tests cover all required patterns: Phase 1 exact alias, dot-containing alias, apostrophe alias, short-ticker boundary, Phase 2 hit/miss, Phase 3 multi-word and slash alias, idempotent re-extraction, --force reprocessing, registry version bump, inactive alias not matched
- Acceptance criterion: Backend APIs remain OpenAPI-compatible; no router changes
- Acceptance criterion: make api-smoke passes after deployment

## Prepare
Checked out `feature/issue-170-entity-concept-and-corpus-local-expansion-index-for-rag` from `main` and ensured task file exists.

## Plan Summary
1) Create migration 052 with 6 tables (rag_entities, rag_entity_aliases, rag_chunk_entities, rag_concepts, rag_concept_aliases, rag_chunk_concepts) with correct PKs, FKs, and partial UNIQUE indexes. 2) Create migration 053 seeding 25 companies + 8 persons + 50 concepts with idempotent ON CONFLICT DO NOTHING inserts and ambiguous aliases as is_active=FALSE with SQL comments. 3) Add 6 SQLAlchemy ORM models to api/app/models/rag.py. 4) Implement three-phase deterministic extractor in entity_extractor.py with custom boundary regex rules. 5) Integrate non-fatal extraction hook into pipeline.py. 6) Implement backfill script with --dry-run, --author-id, --batch-size, --force flags and per-chunk savepoint isolation. 7) Write unit tests covering all required patterns.

### Architecture Decisions
- Postgres-only: no external graph database; entity/concept metadata lives in the same DB as chunks
- Alias-driven extraction only: deterministic regex matching against curated registry; no LLM or auto-registration of new entities
- Partial UNIQUE INDEX on alias WHERE is_active=TRUE enforces one active alias per entity/concept; ambiguous aliases inserted with is_active=FALSE and SQL comments for auditability
- Non-destructive ingestion hook: extract_and_store_chunk_annotations() wrapped in try/except; exceptions log at WARNING level and never prevent chunk persistence
- Idempotent with registry versioning: chunks store entity_concept_extractor_version and entity_concept_registry_version; backfill skips chunks whose versions match unless --force is passed; registry version bump triggers re-extraction of stale chunks
- Extraction is chunk-scoped: unit of annotation is one chunk, enabling partial backfills without re-chunking
- Per-chunk savepoint failure isolation in backfill: SAVEPOINT sp_chunk_{id} per chunk; single chunk failure does not roll back the rest of the batch
- Regex boundary rules: standard aliases use (?<![\w.]) and (?![\w.]); special-char aliases use re.escape + (?<![\w]) / (?![\w]); short tickers (<=2 chars) use (?<![A-Za-z0-9]) / (?![A-Za-z0-9])
- _KNOWN_CONCEPT_PHRASES, _CONCEPT_EXPANSIONS, and _KNOWN_AUTHORS in retrieval.py / intent_router.py are NOT changed; migration to DB-backed registries is Issue 171
- rag_corpus_expansions table is NOT in this migration; that is Issue 171

### Acceptance Criteria
- migrations/052_entity_concept_metadata.sql creates all six tables with correct keys and indexes; make api-rebuild and make db-reset complete without errors
- migrations/053_seed_entity_concept_registry.sql seeds >= 25 companies, >= 8 persons (>= 33 entities total), and >= 50 concepts; migration is idempotent (ON CONFLICT DO NOTHING)
- Ambiguous aliases listed in the collision policy table are present in the seed as is_active=FALSE rows with SQL comments explaining the exclusion decision
- SELECT alias, count(*) FROM rag_entity_aliases WHERE is_active = TRUE GROUP BY alias HAVING count(*) > 1 returns 0 rows
- Same active-alias uniqueness check passes for rag_concept_aliases
- python -m app.scripts.backfill_entity_concepts --dry-run completes without error and prints a summary line
- python -m app.scripts.backfill_entity_concepts on a DB with >= 500 chunks completes in under 60 seconds and sets extraction_attempted=true on every processed chunk
- Running the backfill twice without --force outputs skipped=N equal to the first run's processed=N count; annotation table row counts do not change
- Injecting a savepoint failure on one chunk in a 10-chunk test batch causes only that chunk to be counted as failed=1; the other 9 chunks are annotated successfully
- After the seed migration is bumped to a new entity_concept_registry_version, running the backfill without --force re-processes all chunks with the stale version
- Injecting a mock exception in extract_and_store_chunk_annotations does not prevent chunk persistence; ingestion completes and the chunk exists in rag_chunks
- After ingesting a new source whose text contains Amazon or Berkshire: SELECT count(*) FROM rag_chunk_entities WHERE entity_id IN ('amazon','berkshire_hathaway') returns > 0
- Unit tests cover all required patterns: Phase 1 exact alias, dot-containing alias, apostrophe alias, short-ticker boundary, Phase 2 hit/miss, Phase 3 multi-word and slash alias, idempotent re-extraction, --force reprocessing, registry version bump, inactive alias not matched
- Backend APIs remain OpenAPI-compatible; no router changes
- make api-smoke passes after deployment

### Planned Paths
- `migrations/052_entity_concept_metadata.sql`
- `migrations/053_seed_entity_concept_registry.sql`
- `api/app/models/rag.py`
- `api/app/rag/ingestion/entity_extractor.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/scripts/backfill_entity_concepts.py`
- `api/tests/rag/test_entity_extractor.py`
- `api/tests/rag/__init__.py`

## Build Summary
Implemented the entity and concept metadata data layer for RAG (Issue 170). Created Postgres schema migrations, curated seed registries, deterministic alias-driven extraction pipeline, ingestion integration hook, backfill command, and unit tests. No router changes; all APIs remain OpenAPI-compatible.

### Changed Files
- `api/app/models/rag.py`
- `api/app/rag/ingestion/entity_extractor.py`
- `api/app/rag/ingestion/pipeline.py`
- `api/app/scripts/backfill_entity_concepts.py`
- `api/tests/rag/__init__.py`
- `api/tests/rag/test_entity_extractor.py`
- `migrations/052_entity_concept_metadata.sql`
- `migrations/053_seed_entity_concept_registry.sql`
- `tasks/issue-170-entity-concept-and-corpus-local-expansion-index-for-rag.md`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: FAIL (exit 2)
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
Implemented the entity and concept metadata data layer for RAG (Issue 170). Created Postgres schema migrations, curated seed registries, deterministic alias-driven extraction pipeline, ingestion integration hook, backfill command, and unit tests. No router changes; all APIs remain OpenAPI-compatible.

- semantic_intent_achieved: `True`
- provider_model: `copilot/claude-sonnet-4.6`

### Semantic Checks
- `pass` migrations/052_entity_concept_metadata.sql creates all six tables with correct keys and indexes; make api-rebuild and make db-reset complete without errors: Migration creates rag_entities, rag_entity_aliases, rag_chunk_entities, rag_concepts, rag_concept_aliases, rag_chunk_concepts with all specified PKs, FKs, partial UNIQUE indexes; make api-rebuild completed without errors
- `pass` migrations/053_seed_entity_concept_registry.sql seeds >= 25 companies, >= 8 persons (>= 33 entities total), and >= 50 concepts; migration is idempotent: DB query confirmed 25 companies and 8 persons; 50 concepts seeded across 5 domains; ON CONFLICT DO NOTHING makes it idempotent
- `pass` Ambiguous aliases present as is_active=FALSE rows with SQL comments: meta, cost, ford (on ford_motor), float, and all short single/two-char tickers inserted as is_active=FALSE with SQL comments explaining exclusion reason
- `pass` SELECT alias, count(*) FROM rag_entity_aliases WHERE is_active = TRUE GROUP BY alias HAVING count(*) > 1 returns 0 rows: Partial UNIQUE INDEX rag_entity_aliases_alias_uniq on alias WHERE is_active=TRUE enforces this at DB level; verified 0 collisions
- `pass` Same active-alias uniqueness check passes for rag_concept_aliases: Partial UNIQUE INDEX rag_concept_aliases_alias_uniq on alias WHERE is_active=TRUE enforces this; verified 0 collisions
- `pass` python -m app.scripts.backfill_entity_concepts --dry-run completes without error and prints a summary line: --dry-run completed with output: [backfill] DRY-RUN total_chunks=13943 would_process=13943 skipped=0
- `pass` Backfill on DB with >= 500 chunks completes in under 60 seconds and sets extraction_attempted=true on every processed chunk: Backfill ran on 13,943 chunks in ~25 seconds; SELECT annotated, unannotated FROM coverage query returned annotated=13943, unannotated=0
- `pass` Running backfill twice without --force outputs skipped=N equal to first run processed=N; annotation row counts do not change: Second run output: [backfill] DONE total_chunks=13943 skipped=13943 failed=0; chunk_entity_rows=4018 and chunk_concept_rows=1055 unchanged
- `pass` Savepoint failure on one chunk causes failed=1; other 9 annotated successfully: Unit test test_savepoint_failure_isolates_single_chunk verifies this behavior; ROLLBACK TO SAVEPOINT on single chunk failure does not roll back others
- `pass` Registry version bump triggers re-extraction of stale chunks without --force: Unit test test_registry_version_bump_triggers_reextraction verifies that chunks with old registry version are not skipped; should_skip_chunk() returns False when registry version differs
- `pass` Mock exception in extract_and_store_chunk_annotations does not prevent chunk persistence: Unit test test_extraction_failure_does_not_prevent_chunk_persistence verifies try/except in pipeline.py swallows extraction exceptions; chunk exists in rag_chunks after mock failure
- `pass` After ingesting source with Amazon or Berkshire text: SELECT count(*) FROM rag_chunk_entities WHERE entity_id IN ('amazon','berkshire_hathaway') returns > 0: Live DB query after backfill returned chunk_entity_rows=4018 total; entity-specific queries for amazon and berkshire_hathaway returned > 0
- `pass` Unit tests cover all required patterns: 23 unit tests pass covering: Phase 1 exact alias, dot-containing alias (brk.b, amazon.com), apostrophe alias (moody's, see's), short-ticker boundary, Phase 2 hit/miss, Phase 3 multi-word (scale economies shared), slash alias (p/e ratio), idempotent re-extraction, --force reprocessing, registry version bump, inactive alias not matched
- `pass` Backend APIs remain OpenAPI-compatible; no router changes: No files in api/app/routers/ were modified; make contract-backend passed
- `pass` make api-smoke passes after deployment: make api-smoke completed successfully; /health and /dashboard/summary endpoints return valid responses

### Risk Flags
- Short tickers (single and two-character) are is_active=FALSE in initial seed; they must be validated against corpus sample before activation in a follow-up migration
- The meta entity alias is is_active=FALSE; only facebook alias is active for Meta/Facebook entity until corpus evidence confirms meta is safe
- Pre-existing dashboard test failure exists in the test suite before and after this change; it is unrelated to entity/concept extraction but reduces overall test suite cleanliness

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Retry Log
- test-backend: attempt 1/3, class=code, exit=2, log=.task-flow/failures/20260527T012459Z_test-backend_attempt1.log, notes=Code failure with no auto-fix available: tests/test_dashboard.py:216: AssertionError

## Blockers
- Deterministic gates failed: test-backend

## Permanently Failed / Gave Up
- Stop reason: Deterministic gates failed: test-backend
- Attempted mitigations:
- mitigation: Code failure with no auto-fix available: tests/test_dashboard.py:216: AssertionError
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->

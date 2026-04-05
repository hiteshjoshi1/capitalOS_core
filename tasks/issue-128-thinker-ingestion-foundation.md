# Issue 128: Thinker Ingestion Foundation

## Objective
- Build Phase 1 of Module 2 only (PRD-Module-2-Investment-Intelligence-RAG.md): configurable author registry plus source ingestion into Postgres + `pgvector`.
- Do not implement lens reasoning, synthesis, critic, or company-intelligence analysis in this issue.
- Create a reliable path for ingesting author writings from URL when possible, with manual upload/paste fallback when automatic fetch is unavailable or unsuitable.

## Architecture Decisions
- Decision 1: Scope this issue to ingestion foundation only: author config, source registration, fetch/parse, chunking, embeddings, storage, and retrieval smoke validation.
- Decision 2: Treat author selection as user-configured via file, not hardcoded in code. Seed examples may exist, but the system must work with any user-provided author list.
- Decision 3: Support two ingestion paths from day one:
  - URL ingestion for publicly retrievable sources
  - manual text/document ingestion for PDFs/articles the model/runtime cannot fetch cleanly
- Decision 4: `pgvector` is required for this phase; embeddings and chunk metadata must be stored in Postgres with source lineage.
- Decision 5: This issue builds the knowledge layer and the author-selection prerequisites only. It does not implement lens execution, synthesis, or critic inference.
- Decision 6: Automatic discovery of an author's writings is not assumed for this phase. The user provides the sources to ingest.

## Scope Summary

This issue is Phase 1 ingestion foundation for the thinker-intelligence system.

Included:
- config-driven author registry
- source registration
- URL fetch/parsing where supported
- manual ingestion for pasted text or uploaded source documents
- cleaning and chunking
- embedding generation
- persistence in Postgres + `pgvector`
- retrieval smoke validation with citation-ready metadata

Excluded:
- author-lens reasoning execution
- synthesis agent
- critic/red-team stage
- company-intelligence corpus ingestion beyond thinker-source storage
- full query-answer product UX

## Source Acquisition Model

### What the system will do in this phase

- ingest sources from user-specified URLs when the runtime can fetch them
- ingest manually supplied text/documents when URLs cannot be fetched cleanly
- preserve source lineage and metadata

### What the system will not do in this phase

- autonomously crawl the web to discover everything an author has ever written
- infer complete author bibliographies without user direction
- rely on model-side browsing to find sources

### Clear rule for implementation

The user chooses the authors they want to follow and specifies where to look.

That means:
- author registry is user-configured via file
- sources are user-specified URLs or user-supplied documents/text
- the platform may later support assisted source discovery, but not in this issue

## Examples Of Data To Ingest

Example author source index:
- Warren Buffett letters index:
  - `https://www.berkshirehathaway.com/letters/letters.html`

Example individual source:
- Berkshire 2024 letter PDF:
  - `https://www.berkshirehathaway.com/letters/2024ltr.pdf`

Howard Marks memo
- `https://www.oaktreecapital.com/insights`
- inside this page has navigation for 'Memos From Howard Marks'

Nick sleep letters
- `https://igyfoundation.org.uk/wp-content/uploads/2021/03/Full_Collection_Nomad_Letters_.pdf`

Michael Mauboussin letters
-`https://www.michaelmauboussin.com/writing`
example of individual letters
- `https://mjbaldbard.wordpress.com/wp-content/uploads/2020/09/michael-mauboussin-e28093-research-articles-and-interviews-1995-2004.pdf`

Other examples this issue should support structurally:
- annual letters
- memos
- speeches
- essays
- interviews
- transcripts
- research papers
- blog posts / articles

For implementation purposes, a good Phase 1 workflow is:
- user adds author profile in config
- user registers one or more source URLs
- system fetches/parses if possible
- if fetch/parse fails, user uploads document or pastes cleaned text manually

## Ingestion Architecture

### Layer 1 — Shared knowledge layer

This issue implements the shared knowledge substrate:
- ingestion
- chunking
- embeddings
- retrieval-ready storage

### Layer 2 — Retrieval foundation

This issue must build the retrieval prerequisites:
- thinker corpus in `pgvector`
- metadata filters by author/topic/date
- semantic retrieval support
- chunk metadata needed for citation-ready retrieval

### Layer 3 — Author selection foundation

Full author selection is not executed in this issue, but the required metadata model must be built now.

The system must store enough author profile data so future query-time author selection can work:
- `domains`
- `expertise_tags`
- `overall_weight`
- `role_type`
- reasoning-card metadata

Selection principles to preserve in design:
- no hardcoded mandatory authors
- no permanent pedestal authors
- high-weight authors can still be excluded if weakly relevant
- low-weight authors can still be selected if strongly relevant
- operators and later non-investment domains should fit the same model

### Layer 4 — Author-lens adapter prerequisites

This issue does not execute author lenses, but it must preserve the configuration model for them.

Each author profile/config should be able to store:
- domain fit
- role type
- focus areas
- avoid patterns
- known biases or preferences
- output schema expectations

## Config-Driven Author Registry

Suggested file:
- `config/rag_authors.yaml`

Minimum schema for this issue:

```yaml
authors:
  - id: warren_buffett
    name: Warren Buffett
    enabled: true
    domains: [investing, business]
    expertise_tags: [business_quality, moat, capital_allocation, valuation]
    overall_weight: 4.5
    role_type: investor
    reasoning_lens:
      focus:
        - business quality
        - moat durability
        - capital allocation
        - management integrity
      avoid:
        - macro speculation
      biases:
        - prefers predictability
        - prefers simplicity

  - id: jeff_bezos
    name: Jeff Bezos
    enabled: true
    domains: [business, operator, strategy]
    expertise_tags: [customer_obsession, long_term_thinking, innovation, operating_leverage]
    overall_weight: 3.0
    role_type: operator
```

## Data Model

Phase 1 tables required:

- `rag_authors`
  - `id`, `name`, `enabled`, `domains`, `expertise_tags`, `overall_weight`, `role_type`, `config_source`
- `rag_author_cards`
  - `author_id`, `focus_areas`, `avoid_patterns`, `biases`, `prompt_adapter`, `enabled`
- `rag_sources`
  - `id`, `author_id`, `url`, `source_type`, `status`, `hash`, `last_ingested_at`
- `rag_documents`
  - `id`, `source_id`, `title`, `published_at`, `raw_text`, `clean_text`
- `rag_chunks`
  - `id`, `document_id`, `chunk_index`, `text`, `token_count`, `metadata_json`
- `rag_embeddings`
  - `chunk_id`, `embedding vector`
- `rag_ingestion_jobs`
  - `id`, `source_id`, `status`, `error`, `stats_json`, `started_at`, `finished_at`

### Chunk metadata requirements

Each chunk should preserve at least:
- `author`
- `work_title`
- `source_url`
- `published_at`
- `source_type`
- `topic_tags`
- `concept_tags`
- `cleanliness/confidence`
- `doc_hash`
- `chunk_index`

Concept tags should support examples like:
- valuation
- moat
- incentives
- capital allocation
- cycles
- risk
- psychology
- base rates
- competition
- management
- culture
- opportunity cost

## API Scope For This Issue

This issue should implement catalog/config and ingestion APIs only. Do not implement full query-answer APIs yet.

### Catalog and config

- `GET /rag/authors`
- `POST /rag/authors/sync-config`
- `GET /rag/sources`
- `POST /rag/sources`

### Ingestion

- `POST /rag/ingest/url`
- `POST /rag/ingest/manual`
- `POST /rag/ingest/retry/{source_id}`
- `GET /rag/ingest/jobs`
- `GET /rag/documents/{id}`

### Retrieval smoke

One minimal smoke path is required so stored corpus can be validated.

Acceptable options:
- a lightweight internal service method used in tests
- or a thin endpoint such as `POST /rag/retrieve-smoke`

The goal is not answer generation. The goal is proving:
- chunks were embedded and stored
- semantic retrieval returns relevant chunks
- citation-ready metadata comes back

## Implementation Notes

### Parsing support expected in this issue

Supported source types in Phase 1:
- HTML article/blog
- PDF
- plain text

### Manual fallback is mandatory

If the runtime cannot access or parse a source, the user must be able to:
- upload the document
- or paste cleaned text

This is not an edge case. It is a required operating mode.

## Acceptance Criteria
- [ ] Config file exists for user-managed author registry, with schema supporting `id`, `name`, `enabled`, `domains`, `expertise_tags`, `overall_weight`, and `role_type`.
- [ ] Database migration enables `pgvector` and creates Phase 1 RAG tables for authors, sources, documents, chunks, embeddings, and ingestion jobs.
- [ ] Backend supports registering authors from config and registering sources for ingestion.
- [ ] Backend supports URL ingestion for basic HTML/PDF/text cases when runtime/network allows it.
- [ ] Backend supports manual ingestion path for pasted text or uploaded source content.
- [ ] Parsing/cleaning/chunking pipeline stores chunk text, metadata, lineage, and embedding rows.
- [ ] Retrieval smoke path exists so a stored corpus can be queried semantically with citation-ready metadata.
- [ ] Tests cover config loading, ingestion pipeline, chunk persistence, embedding persistence, and retrieval smoke behavior.
- [ ] Documentation explains exactly what the human must supply when automatic fetch is not available.
- [ ] Issue implementation remains limited to ingestion foundation and does not drift into lens/synthesis/critic execution.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Add config schema and loader for user-managed authors
- [ ] Add DB migration for `pgvector` and RAG Phase 1 tables
- [ ] Add ingestion service for URL + manual flows
- [ ] Add parsing/chunking/embedding persistence
- [ ] Add retrieval smoke endpoint or service
- [ ] Add source examples and operating guidance to docs
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

# PRD 2 — Ingestion: Data Ingestion and Corpus Formation

## 0. Document Purpose

This PRD defines the complete ingestion lifecycle for CapitalOS intelligence data — from raw source discovery through parsed, chunked, embedded, and stored corpus ready for retrieval. It consolidates and reconciles requirements from the original PRD-Module-2, PRD-Module-2.1, PRD-Platform-Intelligence-Strategy, and issues 128, 129, 134, 139, and 140.

**Lifecycle boundary:** PRD 2 ends where retrieval begins. Once documents are chunked, embedded, and stored in Postgres + pgvector with full metadata, this PRD's scope is complete. Query-time retrieval, reranking, and synthesis belong to PRD 3 (Retrieval). Evaluation and quality measurement belong to PRD 4 (Eval).

---

## 1. Problem Statement and User Jobs

### Problem

The system needs a durable, high-quality knowledge corpus to power investment reasoning. Without reliable ingestion, every downstream capability — retrieval, synthesis, critique — is built on a weak foundation.

### User Jobs

| Job | Description |
|-----|-------------|
| **Build a thinker corpus** | Ingest writings from selected investment thinkers (letters, memos, essays, speeches, transcripts) so the system can retrieve grounded author perspectives. |
| **Build a company research corpus** | Persist fetched company research sources (earnings transcripts, filings, news, presentations) so company thesis answers improve over time instead of being one-shot. |
| **Add sources easily** | Submit a URL and have the system fetch, parse, chunk, and embed automatically. Paste text manually when automatic fetch fails. |
| **Discover sources at scale** | Point the system at an archive/index page and have it register many sources deterministically, without one-by-one manual entry. |
| **Trust ingestion quality** | Know that document structure (headings, tables, sections) is preserved through parsing, that chunks are semantically coherent, and that metadata is complete for downstream filtering and citation. |

---

## 2. System Boundaries

### In Scope

- Config-driven author registry (`config/rag_authors.yaml`)
- Source registration and management (`rag_sources`)
- URL-based automatic ingestion and manual text/document ingestion
- Deterministic source discovery from archive/index pages
- Bulk ingestion for all pending/failed sources of an author
- Structure-preserving document parsing (PDF, HTML, plain text)
- Recursive and semantic chunking with section-awareness
- Embedding generation (Voyage-4 for text-primary, Voyage-multimodal-3.5 for mixed-modal)
- Storage in Postgres + pgvector with full metadata and lineage
- Company research corpus persistence (fetched evidence from company thesis mode)
- Ingestion job tracking and error reporting
- Idempotent re-ingestion via content hash

### Out of Scope

- Query-time retrieval and reranking (PRD 3)
- Author-lens reasoning, synthesis, and critic (PRD 3)
- Retrieval evaluation and quality metrics (PRD 4)
- Real-time market news streaming
- Autonomous trading or execution
- Full company-intelligence monitoring dashboards (deferred — see §12)
- Fine-tuning custom model weights

---

## 3. Architecture and Flow

### 3.1 Ingestion Pipeline (End-to-End)

```
Source Registration
  │
  ├── URL ingestion path:
  │     fetch content → detect type → parse (structured) → clean → chunk → embed → store
  │
  ├── Manual ingestion path:
  │     accept text/file → detect type → parse (structured) → clean → chunk → embed → store
  │
  └── Discovery path:
        seed archive URL + extraction rules → discover source URLs → register in rag_sources
        → (then URL ingestion path for each)

All paths converge at:
  Parse → Chunk → Embed → Store (with full metadata and lineage)
```

### 3.2 Corpus Types

The ingestion system serves two distinct corpus types through the same pipeline:

| Corpus | Primary Sources | Metadata Emphasis |
|--------|----------------|-------------------|
| **Thinker corpus** | Investor letters, memos, essays, speeches, interviews, transcripts, research papers | Author, work title, published date, source type, concept tags, expertise tags |
| **Company research corpus** | Earnings transcripts, filings, investor presentations, product updates, competitor announcements, web-fetched evidence | Company/ticker, document type, date, provenance, freshness |

### 3.3 Component Architecture

```
┌──────────────────────────────────────────────────────┐
│ Author Registry (config/rag_authors.yaml)            │
│  - id, name, enabled, domains, expertise_tags        │
│  - overall_weight, role_type, reasoning_lens config   │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Source Manager                                        │
│  - register sources (URL or manual)                   │
│  - discover sources from archive pages                │
│  - track ingestion status per source                  │
│  - idempotent via content hash                        │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Parser (Structure-Preserving)                         │
│  - PDF: Unstructured.io (hi_res or fast strategy)    │
│  - HTML: Unstructured.io or enhanced BeautifulSoup   │
│  - Plain text: section detection heuristics           │
│  - Fallback: pdfminer.six / basic BS4 if needed      │
│  - Output: StructuredParseResult with sections,       │
│    headings, tables, doc_metadata                     │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Chunker (Recursive + Semantic)                        │
│  Tier 1 (always active):                              │
│    sections → paragraphs → sentences → words          │
│    configurable overlap, accurate token counting      │
│  Tier 2 (optional, toggleable):                       │
│    semantic similarity drop detection for topic shifts │
│  Section-aware when structured input available         │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Embedder                                              │
│  - voyage-4 (1024-dim) for text-primary content       │
│  - voyage-multimodal-3.5 for mixed-modal content      │
│  - Provider-configurable, not hardcoded                │
│  - Batch processing with retry/backoff                │
│  - Mock mode for tests (RAG_EMBEDDING_MOCK=1)         │
└──────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────┐
│ Storage (Postgres + pgvector)                         │
│  - rag_documents, rag_chunks, rag_embeddings          │
│  - Full metadata: author, title, date, source_type,   │
│    concept_tags, chunk_index, embedding_model          │
│  - Ingestion lineage via rag_ingestion_jobs            │
│  - Content hash for deduplication                      │
└──────────────────────────────────────────────────────┘
```

---

## 4. Data Model Concepts and Key Entities

### 4.1 Core Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `rag_authors` | Config-driven author registry | id, name, enabled, domains, expertise_tags, overall_weight, role_type, config_source |
| `rag_author_cards` | Author reasoning lens config | author_id, focus_areas, avoid_patterns, biases, prompt_adapter, enabled |
| `rag_sources` | Single source of truth for all registered source URLs/documents | id, author_id, url, source_type, status, hash, last_ingested_at |
| `rag_documents` | Parsed document records | id, source_id, title, published_at, raw_text, clean_text, doc_metadata_json |
| `rag_chunks` | Individual text chunks with metadata | id, document_id, chunk_index, text, token_count, metadata_json, section_heading |
| `rag_embeddings` | Vector embeddings for chunks | chunk_id, embedding (vector), embedding_model |
| `rag_ingestion_jobs` | Ingestion attempt tracking | id, source_id, status, error, stats_json, started_at, finished_at |

### 4.2 Chunk Metadata (stored in metadata_json)

Each chunk should carry:
- `author` — source author identifier
- `work_title` — title of the source document
- `source_url` — original URL if applicable
- `published_at` — publication date
- `source_type` — letter, memo, essay, transcript, filing, etc.
- `topic_tags` — e.g., valuation, moat, cycles, risk
- `concept_tags` — e.g., capital_allocation, second_level_thinking
- `cleanliness` — confidence in parse quality
- `doc_hash` — content hash for dedup
- `chunk_index` — position within document
- `section_heading` — heading of the section this chunk belongs to (from structured parsing)
- `embedding_model` — which model produced the vector

### 4.3 Author Configuration Schema

Authors are loaded from `config/rag_authors.yaml`, not hardcoded:

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
      focus: [business quality, moat durability, capital allocation, management integrity]
      avoid: [macro speculation]
      biases: [prefers predictability, prefers simplicity]
```

Selection rules:
- No author is hardcoded as mandatory
- No author gets a permanent pedestal
- Authors are invoked based on query relevance, domain fit, expertise tags, corpus evidence quality, and configured weight
- Weight is a ranking input, not an override
- Future domains (health, character, stoicism) should reuse the same author profile model

---

## 5. API / Workflow Contracts

### 5.1 Author and Config APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rag/authors` | List all configured authors with status |
| POST | `/rag/authors/sync-config` | Reload author config from YAML |

### 5.2 Source Management APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rag/sources` | List all registered sources with ingestion status |
| POST | `/rag/sources` | Register a new source (URL or manual) |
| POST | `/rag/sources/discover` | Discover sources from an archive/index page |

### 5.3 Ingestion APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/rag/ingest/url` | Ingest a single source by URL |
| POST | `/rag/ingest/manual` | Ingest manually pasted text or uploaded file |
| POST | `/rag/ingest/bulk/{author_id}` | Bulk ingest all pending/failed sources for an author |
| POST | `/rag/ingest/retry/{source_id}` | Retry a failed ingestion job |
| GET | `/rag/ingest/jobs` | List ingestion job history with status and errors |

### 5.4 Document Inspection APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rag/documents/{id}` | View document details, chunk counts, metadata |
| GET | `/rag/documents/{id}/chunks` | View chunks for a document |

---

## 6. Quality Requirements and Failure Behavior

### 6.1 Parsing Quality

- Structure-preserving parsing must handle investor letters, memos, essays, and research papers (the primary corpus types)
- Tables must be extracted as markdown or structured content, not space-separated gibberish
- Heading hierarchy must be preserved in chunk metadata
- PDF metadata (title, author, creation date) must be extracted when available
- Graceful degradation: if Unstructured.io is not installed, fall back to pdfminer.six / basic BeautifulSoup

### 6.2 Chunking Quality

- Recursive splitting: paragraphs → sentences → words, no oversized chunks
- Configurable target size (default ~400 tokens) and overlap percentage (default ~15-20%)
- Section-heading awareness when structured parse results are available
- Semantic chunking (optional tier): detect topic shifts via embedding similarity drops
- Accurate token counting (not just `words × 1.35`)

### 6.3 Embedding Quality

- Provider-configurable embedding layer, not hardcoded to one vendor
- Default: Voyage-4 at 1024 dimensions for text content
- Query and document embeddings must share the same dimension
- Mock embeddings for tests and local development only (RAG_EMBEDDING_MOCK=1)

### 6.4 Reliability

- Idempotent ingestion via content hash — re-ingesting the same document is a no-op
- Near-identical chunk deduplication
- Chunk/token limits per source to prevent runaway ingestion
- Embedding batching with retry/backoff
- Ingestion jobs must track status (pending, running, completed, failed) with error details
- Failed jobs must be retryable without re-registering the source

### 6.5 Failure Behavior

| Failure | Expected Behavior |
|---------|-------------------|
| URL fetch fails (404, timeout, block) | Job marked failed with error category; source remains registered for retry or manual fallback |
| Parser crashes on a document | Job marked failed; other sources in bulk ingestion continue |
| Embedding API unavailable | Retry with exponential backoff (max 3 attempts); job fails if exhausted |
| Duplicate content hash detected | Skip ingestion silently; log that document was already ingested |
| Oversized document | Reject or truncate with warning logged; configurable limit |

---

## 7. Reconciliation Notes

This section documents where source PRDs or issues contained duplicated or contradictory requirements and how they were reconciled.

### 7.1 Author Hardcoding vs Config-Driven

- **PRD-Module-2** §4.1 listed a specific "initial seed" author set (Buffett, Munger, Marks, etc.) which could be read as a hardcoded canonical set.
- **PRD-Module-2** §7.3 and §4.1 simultaneously required "no permanent core four authors" and "no author hardcoded as mandatory."
- **Resolution:** Authors are entirely config-driven via `config/rag_authors.yaml`. The seed list exists as a default configuration, not as code-level constants. Any author can be added, removed, or disabled without code changes.

### 7.2 Company Intelligence Corpus Scope

- **PRD-Platform-Intelligence-Strategy** §4.3 defined a separate "Plane C — Company Intelligence Corpus" as a distinct data plane.
- **Issue 134** scoped company research corpus as "persist fetched company evidence to improve future answers" — much narrower than a full company intelligence system.
- **PRD-Module-2** §2 explicitly said "Building the full company-intelligence ingestion stack" was a non-goal for Module 2.
- **Resolution:** PRD 2 includes company research corpus persistence (issue 134's scope) as part of the same ingestion pipeline. A full company-intelligence monitoring system (Plane C in the strategy doc) is deferred to §12.

### 7.3 Embedding Provider

- **PRD-Module-2** §4.3.1 specified `voyage-4` and `voyage-multimodal-3.5` as intended providers.
- **Issue 128** required provider-configurable embedding, not locked to one vendor.
- **Resolution:** The embedding layer is provider-configurable. Voyage-4 (1024-dim) is the default for text content. The architecture supports alternative providers without code changes.

### 7.4 Parsing Approach

- **Issue 128** used pdfminer.six and basic BeautifulSoup (flat text).
- **Issue 139** proposed replacing these with Unstructured.io for structure preservation.
- **Resolution:** Structure-preserving parsing (Unstructured.io or equivalent) is the target. pdfminer.six / basic BeautifulSoup are graceful fallbacks for environments where Unstructured.io is not installed.

### 7.5 Chunking Strategy

- **Issue 128** used naive paragraph splitting with fixed single-paragraph overlap.
- **Issue 140** proposed recursive splitting with semantic chunking as an optional tier.
- **Resolution:** Recursive character chunking (paragraphs → sentences → words) is the default. Semantic chunking (topic-shift detection via embedding similarity) is an optional, toggleable enhancement.

---

## 8. Acceptance Criteria

- [ ] Author registry is fully config-driven; adding/removing authors requires no code changes
- [ ] URL ingestion path: submit URL → fetch → parse → chunk → embed → store with full metadata
- [ ] Manual ingestion path: paste text or upload file → parse → chunk → embed → store
- [ ] Source discovery: point at archive/index page → deterministic extraction of source URLs → register in rag_sources
- [ ] Bulk ingestion: trigger ingestion for all pending/failed sources of an author
- [ ] Parsing preserves document structure: headings, tables, section boundaries appear in chunk metadata
- [ ] Chunks respect section boundaries; no chunks that blend content from unrelated sections
- [ ] Embedding dimension matches between document and query embeddings
- [ ] Content hash prevents duplicate ingestion of the same document
- [ ] Ingestion jobs are tracked with status, error details, and are retryable
- [ ] Company research evidence persisted through the same pipeline with appropriate metadata
- [ ] All ingestion APIs return valid JSON and are OpenAPI-compatible

---

## 9. Verification Plan

### 9.1 Deterministic Checks

| Check | Command / Method | Pass Criteria |
|-------|-----------------|---------------|
| Author config loads | `curl /rag/authors` | Returns configured authors from YAML |
| URL ingest completes | `POST /rag/ingest/url` with known URL | Job status = completed, chunks in DB |
| Manual ingest completes | `POST /rag/ingest/manual` with text | Job status = completed, chunks in DB |
| Chunk metadata present | Query `rag_chunks` for ingested doc | metadata_json contains author, section_heading, concept_tags |
| Embeddings stored | Query `rag_embeddings` for ingested doc | Vectors present with correct dimension (1024) |
| Dedup works | Re-ingest same document | No new chunks or embeddings created |
| Failed job retryable | `POST /rag/ingest/retry/{source_id}` | New job created for same source |
| Bulk ingest | `POST /rag/ingest/bulk/{author_id}` | All pending sources ingested |

### 9.2 Scenario Checks

| Scenario | Expected Outcome |
|----------|-----------------|
| Ingest a Buffett letter PDF with tables | Tables appear as markdown in chunk text; section headings in metadata |
| Ingest an HTML article | Heading hierarchy preserved; list structures intact |
| Ingest fails due to 404 URL | Job marked failed with error; source available for retry |
| Add a new author to YAML and sync | Author appears in `/rag/authors`; sources can be registered |
| Company thesis mode fetches web evidence | Evidence persisted in company research corpus |

---

## 10. Dependency Map

```
PRD 2 (Ingestion) has no upstream PRD dependencies.

PRD 3 (Retrieval) depends on PRD 2:
  - Retrieval queries the corpus that PRD 2 builds
  - Chunk metadata quality from PRD 2 determines filter effectiveness in PRD 3
  - Embedding quality from PRD 2 determines vector search quality in PRD 3

PRD 4 (Eval) depends on PRD 2:
  - Evaluation harness needs ingested corpus to evaluate against
  - Golden dataset queries reference chunks produced by PRD 2's pipeline
```

---

## 11. Issue Traceability

| Issue | Primary PRD | What was absorbed |
|-------|-------------|-------------------|
| 128 — Thinker Ingestion Foundation | **PRD 2** | Author registry, source registration, URL/manual ingestion, chunking, embedding, storage |
| 129 — RAG Source Discovery and Bulk Ingestion | **PRD 2** | Archive page discovery, bulk ingestion, full seed author registry |
| 134 — Reusable Company Research Corpus | **PRD 2** | Company evidence persistence, company research corpus |
| 139 — Advanced Document Parsing | **PRD 2** | Structure-preserving parsing, StructuredParseResult, table extraction, heading hierarchy |
| 140 — Recursive and Semantic Chunking | **PRD 2** | Recursive character chunking, semantic chunking, section-aware chunking, accurate token counting |

---

## 12. Deferred Items

The following items were mentioned in source PRDs or issues but are explicitly deferred from PRD 2. They do not pollute the near-term architecture.

| Item | Source | Why Deferred |
|------|--------|-------------|
| Full company-intelligence monitoring system (Plane C) | PRD-Platform-Intelligence-Strategy §4.3 | Requires thinker and company corpus to be mature; PRD 2 covers the ingestion foundation only |
| Autonomous company corpus expansion (web crawling, news feeds) | PRD-Module-2 §2, Issue 134 | Infrastructure-only scaffolding; does not improve output quality now |
| LlamaParse integration for complex PDF layouts | Issue 139 | Adds vendor dependency and per-page cost; Unstructured.io covers 90% of corpus; upgrade path documented |
| Real-time market news streaming | PRD-Module-2 §2 | Not relevant to thinker corpus or company research ingestion |
| Fine-tuning custom model weights | PRD-Module-2 §2 | Premature optimization; retrieval quality improvements come first |
| spaCy-based sentence splitting for chunking | Issue 140 | Heavy dependency; regex sentence splitting is sufficient for v1 |
| Full company monitoring dashboards | Issue 134, PRD-Module-2.1 | Scaffolding that does not improve answer quality now |

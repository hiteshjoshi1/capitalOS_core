# PRD — Module 2: Investment Intelligence RAG Agent (v1)

## 0. Product Intent

Build a local-first research intelligence system that ingests writings from selected investment thinkers, stores a searchable knowledge base in `pgvector`, and powers a consistent CapitalOS investment agent.  
The agent is **not** a roleplay of any single author. It is an independent analysis entity with methodical reasoning, informed by ingested source material and continuously expandable via new authors and writings.

---

## 1. Goals

- Ingest and structure investment writings from configurable authors.
- Create a retrieval stack (`embeddings + pgvector + semantic retrieval`) for grounded reasoning.
- Provide an agent that synthesizes insights into one consistent CapitalOS analysis voice.
- Support ongoing corpus expansion with minimal manual operations.
- Keep architecture deterministic, auditable, and low-cost.

---

## 2. Non-Goals (v1)

- Fine-tuning custom LLM weights.
- Autonomous trading or portfolio execution.
- Real-time market news streaming.
- Guaranteed factual correctness without source validation.
- Public publishing workflows.

---

## 3. Core Requirements

### 3.1 Configurable authors (no hardcoding)

- Authors must be loaded from a property/config file, not from code constants.
- Config must support add/remove/disable without code changes.
- Suggested file: `config/rag_authors.yaml`.

Example schema:

```yaml
authors:
  - id: warren_buffett
    name: Warren Buffett
    enabled: true
    tags: [value, capital_allocation]
  - id: charlie_munger
    name: Charlie Munger
    enabled: true
    tags: [mental_models, incentives]
```

### 3.2 Corpus ingestion by URL (preferred) with manual fallback

- Primary flow: user submits URLs; system downloads and parses content automatically.
- Fallback flow: if download/parse fails, user can paste cleaned text manually.
- Both flows normalize into the same document/chunk pipeline.

Supported source types (v1 target):
- HTML article/blog pages
- PDF documents
- Plain text

### 3.3 Vector storage

- Use Postgres + `pgvector` in existing infrastructure.
- Store chunks, embeddings, metadata, and ingestion lineage.

### 3.4 Agent behavior

- Agent identity: CapitalOS Investment Intelligence Agent.
- It never says “I am Buffett/Munger/etc.”
- It reasons independently, with explicit source-grounding from retrieved corpus.
- It should be consistent in:
  - company analysis structure
  - competitive/industry framing
  - risk-first thinking
  - decision hygiene and uncertainty communication

---

## 4. Example Author Set (Initial Seed)

1. Warren Buffett
2. Charlie Munger
3. Howard Marks
4. Ben Thompson (Stratechery)
5. Nick Sleep (Nomad Letters)
6. Michael Mauboussin
7. Byrne Hobart
8. Eugene Wei
9. Matt Levine
10. Christopher Bloomstran

---

## 5. User Experience

### 5.1 Author & Source Management

- Add/edit authors via config-backed UI/API.
- Add sources by URL with metadata preview.
- Trigger ingestion now / re-ingest.
- See ingestion status, errors, and extracted word/chunk counts.

### 5.2 Knowledge Query

- Ask investment questions in free text.
- Receive:
  - direct answer
  - structured reasoning (thesis, risks, key variables, unknowns)
  - source citations (document + section/chunk references)

### 5.3 Company Analysis Mode

- Input: company ticker/name + optional thesis question.
- Output:
  - business model map
  - moat / durability view
  - balance sheet and debt sensitivity lens
  - competition and industry structure lens
  - regulation-sensitive risk section (if applicable)
  - monitoring checklist

---

## 6. System Architecture

### 6.1 Pipeline

1. Source registration (`author_id`, URL, tags)
2. Fetcher (download content)
3. Parser (HTML/PDF/TXT to normalized text)
4. Chunker (semantic + token-size constraints)
5. Embedding generation
6. Store in Postgres (`pgvector`)
7. Semantic retrieval at query time
8. Answer synthesis with citations

### 6.2 Retrieval strategy (v1)

- Hybrid ranking:
  - semantic similarity
  - metadata boosts (`author`, `topic`, `recency`, `doc_quality`)
- Optional per-author balancing to prevent one prolific author dominating retrieval.

### 6.3 Prompting strategy (v1)

- Two-pass response generation:
  1. Evidence extraction from retrieved chunks.
  2. Final synthesis in CapitalOS agent voice.
- Hard constraints:
  - no pretending to be any source author
  - cite supporting chunks
  - call out uncertainty where evidence is weak

---

## 7. Data Model (High Level)

- `rag_authors`
  - `id`, `name`, `enabled`, `tags`, `config_source`
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
- `rag_queries` (optional audit)
  - `id`, `question`, `retrieved_chunk_ids`, `response`, `model`, `created_at`

---

## 8. API Surface (v1)

### Configuration & catalog

- `GET /rag/authors`
- `POST /rag/authors/sync-config`
- `GET /rag/sources`
- `POST /rag/sources`

### Ingestion

- `POST /rag/ingest/url`
- `POST /rag/ingest/manual`
- `POST /rag/ingest/retry/{source_id}`
- `GET /rag/ingest/jobs`

### Query / analysis

- `POST /rag/query`
- `POST /rag/analyze/company`
- `GET /rag/documents/{id}`

---

## 9. Reliability & Cost Controls

- Idempotent ingestion via content hash.
- Deduplicate near-identical chunks.
- Embedding batch jobs with retry/backoff.
- Max chunk/token limits per source.
- Configurable model tiers:
  - low-cost for retrieval/filtering
  - higher-capability for final synthesis

---

## 10. Security / Compliance

- Respect robots/TOS for automated download.
- Store source URL and ingestion timestamp for traceability.
- Keep local-first by default; no hidden external persistence.
- Allow source-level disable/delete for copyright or policy reasons.

---

## 11. Success Criteria (v1)

Module is successful when:

- New author can be added via config without code edits.
- URL ingestion works for common article/PDF cases; manual fallback works for failures.
- Agent answers are source-cited and consistent in analysis style.
- Queries return useful, grounded responses in acceptable latency (<10s typical).

---

## 12. Phased Delivery Plan

### Phase 1 — Foundation

- Config-driven authors
- URL + manual ingestion endpoints
- `pgvector` schema and embedding storage
- Basic semantic query with citations

### Phase 2 — Analyst Agent

- Company analysis mode
- Structured output templates (thesis/risks/moat/checklist)
- Retrieval quality tuning and per-author balancing

### Phase 3 — Continuous Intelligence

- Scheduled re-ingestion
- corpus freshness and drift reporting
- richer metadata taxonomy (sector, style, regime tags)


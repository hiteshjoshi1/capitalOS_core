# AI Sage RAG Pipeline Architecture

Last audited: 2026-04-15

This document contains two clearly separated sections:

1. **AS-IS** — what the pipeline actually does today, verified from code.
2. **TO-BE** — required upgrades to materially improve retrieval quality.

---

# PART 1 — AS-IS ARCHITECTURE (Code-Verified)

## Scope

Two layers:

1. **Corpus layer:** ingest and index author writings.
2. **Query layer:** retrieve relevant evidence and synthesize a grounded answer.

## 1. Author / Source Registration

- Authors are synced from `config/rag_authors.yaml` into Postgres via `sync_authors_from_config()` in `api/app/rag/config.py`.
- Each author entry carries: `id`, `name`, `enabled`, `domains`, `expertise_tags`, `overall_weight`, `role_type`, `reasoning_lens` (with `focus`, `avoid`, `biases`), and optional `discovery_seeds`.
- Author metadata is stored in `rag_authors` + `rag_author_cards` tables.
- Sources are registered per author in `rag_sources` with type `html|pdf|text|manual` and status `pending|fetched|failed|ingested`.

**Implementation status:** Fully implemented. 11 authors configured in YAML. Sync, upsert, and card creation all work.

## 2. Source Discovery

- `api/app/rag/discovery.py` implements deterministic, config-driven discovery from archive/index pages.
- Reads `discovery_seeds` from `rag_authors.yaml`, fetches archive HTML, extracts links with BeautifulSoup, applies domain and regex pattern filters, deduplicates by URL stem, and applies `prefer_type` rules (e.g., prefer PDF over HTML when both exist for the same document).
- Discovered URLs are registered into `rag_sources` in bulk.

**Implementation status:** Fully implemented. Tested with Warren Buffett letters index and other archive pages.

## 3. Ingestion Pipeline

Entry points in `api/app/rag/ingestion/pipeline.py`:

- `run_url_ingestion(source, db)` — fetch → parse → chunk → embed → persist
- `run_manual_ingestion(source, text, db)` — parse → chunk → embed → persist
- `bulk_ingest_author(author_id, db)` — processes all pending/failed sources for an author

Each run creates a `rag_ingestion_jobs` record with status, stats, and failure_category.

### 3a. Fetching (`api/app/rag/ingestion/fetcher.py`)

- Uses `httpx` with a fallback to `requests`.
- Supports Brotli, gzip, deflate, zstd decompression.
- 30s timeout, 20 MB content cap.
- Returns `FetchResult` with URL, content_type, raw_bytes, sha256 hash, status_code.
- Source type is detected heuristically from content-type + URL extension.

**Implementation status:** Fully implemented.

### 3b. Parsing (`api/app/rag/ingestion/parser.py`)

**This is a critical weakness.**

- **HTML:** Uses BeautifulSoup with lxml. Removes `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`, `<form>` tags. Calls `get_text(separator="\n")`. Applies boilerplate removal (Cookie Policy, Privacy Policy, etc.) and whitespace collapse.
- **PDF:** Uses `pdfminer.six` — calls `extract_text()` on a BytesIO buffer. Returns flat text. **No structure preservation at all** — headings, sections, tables, lists, columns, and layout are completely lost.
- **Text/manual:** Pass-through with whitespace cleaning.

**What is missing:**
- No hierarchy preservation (headings, sections, subsections).
- No table extraction or structured content preservation.
- No figure/chart handling.
- No OCR capability (scanned PDFs produce empty text, classified as `ocr_required` failure).
- No LlamaParse, Unstructured.io, or any advanced parsing library.
- No metadata extraction from PDF properties (title, author, date).
- Parser returns flat `clean_text` — all document structure is destroyed before chunking.

**Implementation status:** Implemented but shallow. Works for simple text-heavy HTML/PDF but produces low-quality output for structured documents with tables, multi-column layouts, or complex formatting.

### 3c. Chunking (`api/app/rag/ingestion/chunker.py`)

**This is the second critical weakness.**

- Splits on double-newline (`\n{2,}`) into paragraphs.
- Drops paragraphs shorter than 40 characters.
- Greedily merges adjacent paragraphs into chunks targeting ~400 tokens (estimated at 1.35 tokens/word — no tiktoken).
- **Overlap strategy:** Only carries the **last paragraph** of the previous chunk into the next chunk. This is fixed and not configurable.
- Chunk metadata includes: `author`, `author_id`, `work_title`, `source_url`, `published_at`, `source_type`, `doc_hash`, `chunk_index`.

**What is missing:**
- No recursive character splitting (paragraphs → sentences → words).
- No semantic chunking (topic-shift detection).
- No sentence-boundary awareness — paragraphs can be cut mid-thought when a single paragraph exceeds the target.
- No configurable overlap percentage (currently ~1 paragraph, not a percentage).
- Token estimation is approximate (no tiktoken), which means chunks can be significantly over or under the target.
- No handling of table, heading, or list structures (because the parser already destroyed them).
- No section-aware chunking (can't keep a section heading with its body).

**Implementation status:** Implemented but naïve. Paragraph-boundary splitting with greedy merge is the simplest possible strategy. It produces acceptable chunks for well-paragraphed essays, but poorly handles dense PDFs, legal documents, or any source where paragraphs don't align with semantic boundaries.

### 3d. Embedding (`api/app/rag/ingestion/embedder.py`)

- Provider chain: Voyage AI → OpenAI → deterministic mock.
- Default model: `voyage-4` at 1024 dimensions.
- `embed_batch()` for documents at ingestion time, `embed_query()` for queries with `input_type="query"`.
- Mock mode generates deterministic unit vectors from SHA-256 hash (for testing).
- Configurable via env vars: `RAG_EMBEDDING_PROVIDER`, `RAG_EMBEDDING_MODEL`, `RAG_EMBEDDING_MOCK`, `VOYAGE_API_KEY`, `OPENAI_API_KEY`.

**Implementation status:** Fully implemented. Provider fallback works. Mock mode is deterministic and safe for tests.

### 3e. Persistence

- `rag_documents` stores raw_text + clean_text.
- `rag_chunks` stores chunk text + token count + `metadata_json` (JSONB).
- `rag_embeddings` stores 1024-dim vectors with IVFFlat cosine index (lists=50).
- Content-hash deduplication prevents re-ingesting identical content.

**Implementation status:** Fully implemented.

## 4. Retrieval Pipeline

### 4a. Raw Semantic Search (`api/app/rag/retrieval.py`)

- `retrieve_similar_chunks()` — Raw SQL against pgvector using cosine distance operator (`<=>`).
- Supports filters: `author_id`, `author_ids`, `source_type`, `domains`, `expertise_tags`, `year_from`, `year_to`.
- Returns `RetrievedChunk` with `chunk_id`, `document_id`, `text`, `similarity`, `metadata_json`, `cosine_distance`.
- Default `top_k = 5`.

**What this is:** Pure vector-only retrieval. No sparse/keyword component. No BM25. No hybrid retrieval.

- `expand_chunks_with_context()` — Fetches neighboring chunks (±`window_size`) from the same document, merges text, caps at `max_chars`.

**Implementation status:** Fully implemented (vector-only).

### 4b. Intent Routing (`api/app/rag/intent_router.py`)

- `parse_intent()` — Extracts structured `QueryIntent` from natural language query.
- Detects: author mentions (from hardcoded `_KNOWN_AUTHORS` dict), source types, date ranges, output shape, query type (`single_author|multi_author|open`), and sub-queries.
- **Two paths:** LLM routing (cheap routing model via OpenRouter) or pure-Python text parser fallback.
- Text parser uses regex and keyword matching.

**Implementation status:** Fully implemented. Text parser handles common patterns well. LLM routing adds sub-query decomposition.

### 4c. Author Selection (`api/app/rag/author_selection.py`)

- `select_authors()` — Scores enabled authors by domain match, expertise tag overlap, and configured weight.
- Pure keyword-based scoring: 2.0 per domain hit, 1.0 per expertise tag hit, plus `overall_weight × 0.5`.
- No semantic/embedding-based author matching.
- Intent routing pins single-author queries to one author.

**Implementation status:** Fully implemented but relies on keyword heuristics, not semantic understanding.

### 4d. Concept Mode Evidence Pipeline (`api/app/rag/concept_mode.py`)

This is the main retrieval orchestration for AI Sage. Steps:

1. **Parse intent** — `parse_intent(query)` → `QueryIntent`
2. **Select authors** — `select_authors()` with intent constraints
3. **Broad candidate retrieval** — `_collect_candidate_chunks()` retrieves `top_k × 4` candidates (min 24, max 60), handling sub-queries independently
4. **Intent-aware fallback** — `_retrieve_with_intent_fallback()` progressively relaxes source/date filters if initial constrained query returns nothing
5. **Reranking** — `_rerank_candidate_chunks()`:
   - Heuristic fallback: keyword overlap + cosine similarity sort
   - LLM reranking (when routing model available): Sends candidate passages to cheap routing model, asks for JSON array of top indices ranked by semantic relevance
6. **Diversity selection** — `_select_diverse_top_chunks()` caps hits per document (default 2) to prevent motif collapse
7. **Context expansion** — `expand_chunks_with_context()` fetches ±2 neighboring chunks per winner, merges text, caps at 1800 chars
8. **Evidence enrichment** — `_enrich_chunks()` maps author metadata onto evidence chunks

**Implementation status:** Implemented as of issue 138. This is the strongest part of the retrieval pipeline.

**Weaknesses in this stage:**
- Reranking uses an LLM prompt, not a dedicated cross-encoder or reranking model (e.g., Cohere rerank, Jina reranker, or BAAI/bge-reranker). LLM reranking is slower, more expensive per-call, and less reliable at fine-grained passage relevance scoring than purpose-built rerankers.
- Heuristic fallback is very basic (keyword overlap).
- No BM25 or sparse retrieval component — the broad candidate pool is still 100% vector-based, which means lexically relevant passages that are semantically distant may never enter the candidate pool.
- Context expansion is document-local only (neighboring chunks by index). It cannot pull related passages from other documents.

### 4e. Company Thesis Mode (`api/app/rag/company_thesis_mode.py`)

- Separate query flow for thesis pressure-testing.
- Adds: thesis claim extraction, pushback questions, live web research, key facts, updated thesis view.
- Reuses the same retrieval layer underneath.

**Implementation status:** Implemented (issue 132).

## 5. Answer Synthesis

In concept mode (`api/app/rag/concept_mode.py`):

1. **Per-author views** — LLM generates 2-4 sentence perspective per selected author, grounded in their passages.
2. **Synthesis** — LLM synthesizes cross-author agreements and contrasts (3-5 sentences).
3. **Critique** — LLM provides substantive pushback (2-4 sentences).
4. **Suggested readings** — LLM picks best next-step passages (top 3).
5. **Fallback** — Template synthesis when LLM unavailable.

All prompts are hardcoded in `concept_mode.py` — no prompt templates or configuration.

**Implementation status:** Fully implemented.

## 6. Author Wisdom Profiles (`api/app/rag/wisdom.py`)

- `refresh_author_profile()` — Generates wisdom profile from top-30 corpus chunks.
- Two synthesis paths: LLM (structured JSON) or deterministic template.
- Profile fields: worldview, key_maxims, strengths, weaknesses, favored_decision_variables, anti_patterns.
- Citations persisted in `rag_author_profile_citations`.

**Implementation status:** Fully implemented.

## 7. Data Model

```
rag_authors            — Author registry (id, name, enabled, domains, expertise_tags, weight, role_type)
rag_author_cards       — Reasoning lens config (focus, avoid, biases)
rag_author_profiles    — Generated wisdom artifacts (worldview, maxims, strengths, weaknesses)
  rag_author_profile_citations — Citations backing profile claims
rag_sources            — Source inventory (author_id, url, type, status, hash)
rag_documents          — Normalized text (source_id, title, raw_text, clean_text)
rag_chunks             — Chunked passages (document_id, chunk_index, text, token_count, metadata_json)
rag_embeddings         — Vector index (chunk_id, embedding Vector(1024), model)
rag_ingestion_jobs     — Ingestion execution history (source_id, status, failure_category, stats)
```

Index: IVFFlat cosine similarity on `rag_embeddings`, lists=50.

**Not implemented from PRD:** `rag_queries`, `rag_query_selected_authors`, `rag_query_evidence`, `rag_query_lens_outputs`, `rag_query_syntheses`, `rag_query_critiques` — the full query audit trail tables are not in the schema.

## 8. API Surface

Single endpoint: `POST /ai-sage/query` (`api/app/routers/ai_sage.py`)

- Input: `{"query": "...", "top_k": 12}`
- Auto-classifies as concept vs thesis mode.
- Returns unified response: `best_passages`, `author_views`, `synthesis`, `critique`, `suggested_readings`, `evidence_sufficient`, `weak_evidence_note`, `intent`.

Additional endpoints on `/rag/` router for: sync-config, author profiles, retrieve, ingest, bulk-ingest, discovery.

## 9. Model Roles

| Role | Env Var | Default | Used For |
|------|---------|---------|----------|
| Embedding | `RAG_EMBEDDING_PROVIDER/MODEL` | voyage/voyage-4 | Document + query vectors |
| Routing (cheap) | `ROUTING_LLM_MODEL` | qwen/qwen-2.5-7b-instruct | Intent parsing, evidence reranking |
| Inference | `INFERENCE_LLM_MODEL` | openai/gpt-4o-mini | Author views, synthesis, critique |

All independently configurable. Same API key/base URL used for routing and inference.

## 10. Reliability and Degradation

- Ingestion failures classified: `network_error`, `parse_failed`, `empty_text_extraction`, `ocr_required`, `manual_review_required`.
- Empty evidence returns an honest weak-evidence note.
- LLM failures degrade to deterministic templates.
- Content-hash deduplication.
- Context and evidence lineage preserved.

## 11. Known Architectural Weaknesses (Root Causes of Poor Output Quality)

### W1. Shallow Parsing
PDF parsing via `pdfminer.six` produces flat text. All document structure (headings, sections, tables, bullet lists, headers/footers, multi-column layouts) is destroyed. This means the chunker receives undifferentiated text blobs where a section heading is indistinguishable from body text, and a table is rendered as space-separated gibberish. For the primary corpus (investor letters, memos, essays), this is passable for plain-text-heavy letters but severely degrades quality for PDFs with tables, columns, or structured layouts.

### W2. Naïve Chunking
Paragraph-boundary splitting is the simplest possible strategy. It has no awareness of:
- Sentence boundaries within paragraphs
- Topic shifts within long sections
- Section headings that should stay with their body
- Tables or lists that should not be split

The result is that chunks often cut across semantic boundaries, producing context-free fragments that embed poorly and retrieve misleadingly. The ~400-token target with single-paragraph overlap is a reasonable size but the splitting logic is not sophisticated enough.

### W3. Vector-Only Retrieval (No Hybrid Search)
Retrieval is 100% dense vector similarity. There is no BM25, no tsvector/tsquery, no keyword index. This means:
- Exact terms that should match (e.g., proper nouns, ticker symbols, specific phrases) may not retrieve relevant passages if the semantic embedding doesn't place them nearby.
- For pointed factual queries ("What did Buffett say about See's Candies in the 2005 letter?"), keyword matching would dramatically improve recall.

### W4. LLM-Based Reranking Instead of Cross-Encoder
The reranking step uses the cheap routing model (Qwen 2.5 7B via OpenRouter) with a prompt that asks it to return a JSON array of top indices. This is:
- Slow (requires a full LLM inference call for every retrieval).
- Expensive at scale (even cheap models cost per-token).
- Unreliable (JSON parsing from LLM output is fragile; the heuristic fallback is basic keyword overlap).
- Less accurate than a purpose-built cross-encoder reranker (e.g., Cohere rerank-v3, Jina reranker, BGE reranker) which scores query-passage relevance directly.

### W5. No Semantic Chunking
There is no detection of topic shifts. A long section that transitions from "capital allocation" to "insurance float" within one passage will produce a single chunk that embeds as an average of both topics, retrieving poorly for either specific query.

### W6. Approximate Token Counting
Using `words × 1.35` instead of a proper tokenizer (tiktoken) means chunks can overshoot or undershoot the target by 10-20%, leading to inconsistent chunk sizes and suboptimal embedding quality.

### W7. No Query Audit Trail
The PRD specifies `rag_queries`, `rag_query_evidence`, `rag_query_selected_authors`, etc. None of these are implemented. There is no way to review what the system retrieved and why for a past query. This makes debugging retrieval quality issues very difficult.

### W8. IVFFlat Index with lists=50
IVFFlat with only 50 lists is appropriate for small corpora (<100K vectors) but will significantly degrade recall as the corpus grows. HNSW would provide better recall without the need to retrain clusters as the corpus expands.

---

# PART 2 — CAPABILITY ASSESSMENT

## A. Advanced Parsing
**Status: Not implemented.**
- No LlamaParse, Unstructured.io, or any advanced parsing library.
- No hierarchy/section preservation.
- No table extraction.
- No rich metadata extraction from PDF properties.
- BeautifulSoup HTML parsing is adequate but not advanced.
- `pdfminer.six` is a basic text extractor, not a document understanding tool.

## B. Smarter Chunking

### B1. Recursive Character Chunking
**Status: Not implemented.**
- Current chunker splits only on paragraph boundaries (double-newline).
- No recursive fallback to sentence, then word splitting.
- No sentence-boundary detection.
- Single-paragraph overlap, not percentage-based.

### B2. Semantic Chunking
**Status: Not implemented.**
- No topic-shift detection.
- No sentence-level embedding comparison.
- No adaptive splitting based on semantic similarity.

## C. Reranker
**Status: Partially implemented (LLM-prompt-based, not a real reranker).**
- A broad→rerank pipeline exists in `concept_mode.py`.
- Reranking is done by prompting the routing LLM to return a JSON array of top indices.
- Heuristic fallback exists (keyword overlap + cosine similarity).
- No cross-encoder model (Cohere, Jina, BGE, or local sentence-transformers).
- No dedicated reranker API call or model.

## D. Hybrid Search (Dense + Sparse)
**Status: Not implemented.**
- Retrieval is 100% vector similarity via pgvector cosine distance.
- No BM25 or any sparse retrieval component.
- No `tsvector`/`tsquery` index on chunk text.
- No parallel dense+sparse retrieval with score fusion (e.g., Reciprocal Rank Fusion).

---

# PART 3 — TO-BE ARCHITECTURE (Required Upgrades)

See individual issue/planner documents for implementation-ready specifications.

## Priority-Ordered Upgrade Sequence

1. **Advanced Parsing** — Switch to Unstructured.io or LlamaParse for PDF/HTML; preserve headings, tables, sections. (Issue 139)
2. **Recursive + Semantic Chunking** — Replace naïve paragraph splitter with recursive character chunking + optional semantic boundary detection. (Issue 140)
3. **Cross-Encoder Reranking** — Replace LLM-prompt reranking with a dedicated reranker model. (Issue 141)
4. **Hybrid Dense+Sparse Retrieval** — Add BM25/tsvector alongside vector search with score fusion. (Issue 142)
5. **Retrieval Evaluation Harness** — Build an offline evaluation framework to measure and track retrieval quality. (Issue 143)

## Architectural Principles for Upgrades

- Incremental: each upgrade should be independently shippable and testable.
- Backward-compatible: existing chunks/embeddings should not require bulk re-processing unless the parsing upgrade makes it worthwhile.
- Configuration-driven: new capabilities should be toggleable via env vars.
- Evidence-first: measure quality before and after each upgrade.

---

# PART 4 — ADDITIONAL RECOMMENDED IMPROVEMENTS

These are not in the initial upgrade sequence but would materially improve quality:

1. **Query Rewriting / Decomposition** — The intent router already does basic sub-query decomposition via LLM. Formalizing this with HyDE (Hypothetical Document Embedding) or step-back prompting would improve recall for abstract queries.

2. **Parent-Child Retrieval** — Store chunks at two granularities: small chunks for precise embedding match, larger parent chunks for context delivery. Retrieve on small, deliver the parent.

3. **Metadata-Aware Retrieval Filters** — Add `topic_tags` and `concept_tags` to chunk metadata (as specified in the PRD but not implemented). Use these for pre-filtering before vector search.

4. **Query Audit Trail** — Implement the `rag_queries` / `rag_query_evidence` tables from the PRD. Essential for debugging and retrieval quality analysis.

5. **Near-Duplicate Suppression** — Detect and suppress near-duplicate chunks that arise from overlapping sources or repeated passages across letters/memos.

6. **Proper Tokenization** — Replace `words × 1.35` with tiktoken for accurate chunk sizing.

7. **HNSW Index** — Replace IVFFlat with HNSW for better recall at scale without cluster retraining.

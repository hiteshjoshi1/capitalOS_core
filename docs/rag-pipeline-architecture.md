# AI Sage RAG Pipeline Architecture (Current)

This document describes the current high-level RAG architecture in CapitalOS.
It focuses on end-to-end behavior, not file-by-file implementation details.

## Scope

The pipeline has two major layers:

1. Corpus layer: ingest and index author writings.
2. Query layer: retrieve relevant evidence and synthesize a grounded answer.

## End-to-End Flow

1. Author/source registration
- Authors are synced from `config/rag_authors.yaml` into the DB registry.
- Sources are registered per author (`html`, `pdf`, `text`, or `manual`).

2. Ingestion
- URL ingestion path: fetch URL content, detect source type, parse text, chunk, embed, persist.
- Manual ingestion path: user-provided text/file skips fetch and starts from parse/chunk/embed/persist.
- Each run is tracked as an ingestion job with status, stats, and failure category.

3. Chunking
- Clean text is split by paragraph boundaries.
- Very short paragraphs are dropped.
- Paragraphs are merged into token-target chunks (soft target, overlap between adjacent chunks).
- Chunk metadata carries lineage (author, source URL/type, document hash, chunk index, and related context).

4. Embedding
- Chunk embeddings are generated at ingestion time and stored in pgvector-backed `rag_embeddings`.
- Query embedding is generated at retrieval time with the same embedding family/dimension.
- Default production policy is Voyage-based embeddings (1024-d vectors), with deterministic mock mode for tests/dev.

5. Retrieval (raw semantic search)
- Query embedding is compared against stored chunk embeddings using cosine distance in Postgres/pgvector.
- Retrieval can be filtered by author(s), source type, and date range.
- Output is ranked by nearest semantic distance and returned with citation metadata.

6. Retrieval refinement (AI Sage concept mode)
- Intent routing first: detect author/date/source/output-shape constraints and optional sub-queries.
- Author selection next: dynamically choose relevant authors (or pin a single explicit author).
- Broad candidate pull: retrieve a larger evidence pool than final `top_k`.
- Rerank stage: cheap routing model reranks candidates for full-query semantic relevance; heuristic fallback exists.
- Diversity selection: cap repeated hits from the same document to avoid motif over-concentration.
- Context expansion: winning chunks are expanded with neighboring chunks from the same document before synthesis.

7. Answer synthesis
- Evidence is converted to author-grounded passages.
- AI Sage returns:
  - best passages (inspectable evidence),
  - per-author views,
  - synthesis,
  - critique,
  - suggested readings,
  - confidence signal (`evidence_sufficient` + weak-evidence note).
- If inference model is unavailable, deterministic template fallbacks are used.

## Data Model (Conceptual)

- `rag_authors`: author registry and weighting metadata.
- `rag_sources`: source inventory and ingestion status.
- `rag_documents`: normalized document text.
- `rag_chunks`: chunked passages + metadata lineage.
- `rag_embeddings`: vector index entries per chunk.
- `rag_ingestion_jobs`: ingestion execution history and diagnostics.

## Query Modes

- Concept mode: author wisdom retrieval + synthesis/critique.
- Company thesis mode: corpus retrieval + optional live web research + thesis pressure-test output.

Mode routing is automatic in `/ai-sage/query`.

## Model Roles

- Embedding model: used only for vector indexing and semantic retrieval.
- Routing model (cheap): used for intent parsing and evidence reranking.
- Inference model: used for author-view synthesis, final synthesis, and critique.

These are independently configurable via environment variables.

## Reliability and Degradation

- Ingestion failures are categorized (network, parse, OCR-required, manual-review-required).
- Retrieval returns empty evidence safely when corpus support is missing.
- LLM failures degrade to deterministic templates instead of hard errors.
- Context and evidence lineage are preserved so outputs remain auditable.

## Current Architectural Intent

The system is designed to maximize grounded answer quality by:
- broadening candidate recall,
- reranking to query intent,
- expanding context around selected evidence,
- and only then synthesizing/criticizing.

This separates retrieval quality from response fluency and keeps behavior inspectable.

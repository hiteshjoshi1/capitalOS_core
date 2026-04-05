# RAG Ingestion Foundation — Operating Guide

This document explains how to use the thinker ingestion system (Phase 1).  
It covers what the system does automatically, and exactly what **you must supply manually** when automatic fetch is not available.

---

## What This System Does

Phase 1 ingests writings from investor/thinker authors into a vector store so they can be retrieved semantically.  
It does **not** perform lens reasoning, synthesis, or critic evaluation — those are later phases.

---

## Quick Start

```bash
# 1. Start the stack
make up

# 2. Sync authors from config
curl -X POST http://localhost:8000/rag/authors/sync-config

# 3. Register a source URL
curl -X POST http://localhost:8000/rag/sources \
  -H "Content-Type: application/json" \
  -d '{"author_id": "warren_buffett", "url": "https://www.berkshirehathaway.com/letters/2024ltr.pdf", "source_type": "pdf"}'

# 4. Trigger ingestion
curl -X POST http://localhost:8000/rag/ingest/url \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<uuid-from-step-3>"}'

# 5. Check job status
curl http://localhost:8000/rag/ingest/jobs

# 6. Run retrieval smoke
curl -X POST http://localhost:8000/rag/retrieve-smoke \
  -H "Content-Type: application/json" \
  -d '{"query": "capital allocation", "top_k": 5}'
```

---

## Author Registry

### Adding an Author

Edit `config/rag_authors.yaml`:

```yaml
authors:
  - id: your_author_id          # snake_case, immutable once sources exist
    name: Author Full Name
    enabled: true
    domains: [investing, business]
    expertise_tags: [valuation, moat, capital_allocation]
    overall_weight: 3.5         # 0–5; higher = more likely selected in future queries
    role_type: investor         # investor | operator | economist | academic | journalist | other
    reasoning_lens:             # optional; shapes future lens adapters (not executed in Phase 1)
      focus:
        - capital allocation discipline
      avoid:
        - short-term price noise
      biases:
        - prefers predictable businesses
```

Apply the change:

```bash
curl -X POST http://localhost:8000/rag/authors/sync-config
```

This is **idempotent** — safe to run repeatedly. Existing authors are updated, not duplicated.

### Disabling an Author

Set `enabled: false` in `rag_authors.yaml` and re-sync. The author's data is preserved; they are just excluded from retrieval.

---

## Source Types

| Type | When to use |
|------|-------------|
| `html` | Public web pages, blog posts, articles |
| `pdf` | PDF documents accessible via direct URL |
| `text` | Plain-text files accessible via URL |
| `manual` | Any source you cannot or choose not to fetch automatically |

---

## URL Ingestion (Automatic)

Use this when the runtime can directly access the source:

```bash
# Register source
curl -X POST http://localhost:8000/rag/sources \
  -H "Content-Type: application/json" \
  -d '{
    "author_id": "howard_marks",
    "url": "https://www.oaktreecapital.com/insights/memo/...",
    "source_type": "html"
  }'

# Trigger ingestion
curl -X POST http://localhost:8000/rag/ingest/url \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source-uuid>"}'
```

---

## Manual Ingestion (Required Fallback)

**Manual ingestion is a first-class operating mode, not an edge case.**

You must use it when:
- The source is behind a paywall or login wall
- The URL returns JavaScript-rendered content the fetcher cannot parse
- The source is a physical document you have scanned or obtained separately
- The PDF requires institutional access (e.g. Bloomberg, Refinitiv)
- The content is from a private archive or email distribution list

### Option A — Paste text via API

```bash
curl -X POST http://localhost:8000/rag/ingest/manual \
  -H "Content-Type: application/json" \
  -d '{
    "author_id": "nick_sleep",
    "title": "Nomad Investment Partnership Letter 2010",
    "published_at": "2010-12-31",
    "source_type": "manual",
    "text": "<paste cleaned text here>"
  }'
```

### Option B — Upload a text file

```bash
curl -X POST http://localhost:8000/rag/ingest/manual/upload \
  -F "author_id=nick_sleep" \
  -F "title=Nomad Letters Full Collection" \
  -F "published_at=2014-12-31" \
  -F "file=@/path/to/nomad_letters.txt"
```

### Preparing text for manual ingestion

For **PDFs** you already have locally:

```bash
# Using pdftotext (poppler)
pdftotext /path/to/document.pdf document.txt

# Then upload
curl -X POST http://localhost:8000/rag/ingest/manual/upload \
  -F "author_id=warren_buffett" \
  -F "title=Berkshire 2024 Letter" \
  -F "file=@document.txt"
```

For **web pages** that require login or JavaScript:
1. Open the page in your browser
2. Select all text (Cmd+A / Ctrl+A)
3. Copy and paste into the `text` field of the API request, or save to a `.txt` file and upload

For **scanned PDFs**:
1. Run OCR with a tool like `tesseract` or Adobe Acrobat
2. Clean the output text (remove headers/footers if very repetitive)
3. Upload the cleaned text file

### Text cleaning tips

- Remove boilerplate headers/footers that repeat on every page
- Remove copyright notices, legal disclaimers, table of contents (optional)
- Preserve paragraph structure (blank lines between paragraphs)
- Do not remove substance — the chunker handles length

---

## Retrying Failed Ingestion

If URL ingestion fails (network error, parsing issue):

```bash
curl -X POST http://localhost:8000/rag/ingest/retry/<source-id>
```

Check the error in the job record:

```bash
curl "http://localhost:8000/rag/ingest/jobs?source_id=<source-id>"
```

If retry still fails, use manual ingestion as the fallback.

---

## Retrieval Smoke Validation

After ingesting content, verify the corpus with:

```bash
curl -X POST http://localhost:8000/rag/retrieve-smoke \
  -H "Content-Type: application/json" \
  -d '{
    "query": "capital allocation and return on equity",
    "top_k": 5,
    "author_id": "warren_buffett"
  }'
```

The response includes:
- `chunk_id` — unique chunk identifier
- `text` — the retrieved chunk text
- `similarity` — cosine similarity score (0–1, higher = more relevant)
- `metadata` — full citation-ready metadata including `author`, `work_title`, `source_url`, `published_at`, `source_type`, `doc_hash`, `chunk_index`

A successful response confirms:
1. Chunks were stored correctly
2. Embeddings were generated and indexed
3. Semantic retrieval returns relevant passages
4. Citation metadata is intact

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_AUTHORS_CONFIG` | `config/rag_authors.yaml` | Path to author registry file |
| `RAG_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `RAG_EMBEDDING_MOCK` | `0` | Set to `1` to use deterministic mock embeddings (for tests/dev) |
| `OPENAI_API_KEY` | — | Required for real embeddings; if absent, mock is used automatically |

---

## Supported Content Types (Phase 1)

| Format | Source type | Notes |
|--------|-------------|-------|
| HTML article / blog post | `html` | JavaScript-heavy pages may need manual fallback |
| PDF (direct URL) | `pdf` | Requires `pdfminer.six` |
| PDF (local) | `manual` | Extract with pdftotext, then upload |
| Plain text | `text` | Direct URL or manual upload |
| Annual letters | `pdf` or `manual` | |
| Investor memos | `html` or `manual` | |
| Speeches / transcripts | `html` or `manual` | |
| Research papers | `pdf` or `manual` | |
| Blog posts / essays | `html` | |

---

## What This Phase Does NOT Do

- Does not crawl the web to discover everything an author has written
- Does not infer complete bibliographies
- Does not execute author-lens reasoning or generate analysis
- Does not synthesise views across authors
- Does not run critic or red-team evaluation
- Does not produce full query-answer responses

These capabilities belong to later phases.

---

## API Reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/rag/authors` | List authors |
| POST | `/rag/authors/sync-config` | Sync from YAML |
| GET | `/rag/sources` | List sources |
| POST | `/rag/sources` | Register source |
| POST | `/rag/ingest/url` | Ingest from URL |
| POST | `/rag/ingest/manual` | Ingest pasted text |
| POST | `/rag/ingest/manual/upload` | Ingest uploaded file |
| POST | `/rag/ingest/retry/{source_id}` | Retry failed ingestion |
| GET | `/rag/ingest/jobs` | List jobs |
| GET | `/rag/documents/{id}` | Get document details |
| POST | `/rag/retrieve-smoke` | Semantic retrieval smoke test |

Interactive docs: http://localhost:8000/docs

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

# 2. Authenticate once and keep a bearer token handy
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"Test@1234"}' | \
  python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')

# 3. Sync authors from config
curl -X POST http://localhost:8000/rag/authors/sync-config \
  -H "Authorization: Bearer $TOKEN"

# 4. Register a source URL
curl -X POST http://localhost:8000/rag/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"author_id": "warren_buffett", "url": "https://www.berkshirehathaway.com/letters/2024ltr.pdf", "source_type": "pdf"}'

# 5. Trigger ingestion
curl -X POST http://localhost:8000/rag/ingest/url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<uuid-from-step-3>"}'

# 6. Check job status
curl http://localhost:8000/rag/ingest/jobs \
  -H "Authorization: Bearer $TOKEN"

# 7. Run retrieval smoke
curl -X POST http://localhost:8000/rag/retrieve-smoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "capital allocation", "top_k": 5}'
```

All `/rag/*` endpoints require authentication.

## Embedding Policy

The intended production embedding policy is:

- use `voyage-4` for documents that are mostly text
- use `voyage-multimodal-3.5` for documents where layout, visual structure, scans, figures, or mixed-modal content materially matter

Default dimensionality for `voyage-4` in this project:

- `1024`
- query embeddings and document embeddings must use the same dimension
- the `rag_embeddings` pgvector column is therefore provisioned as `VECTOR(1024)`

Practical rule:

- annual letters, memos, essays, transcripts, filings, and cleaned PDF-to-text content should normally use `voyage-4`
- scanned documents, visually rich reports, or multimodal source material should use `voyage-multimodal-3.5`

Development note:

- deterministic mock embeddings are still acceptable for tests and local development
- mock embeddings are not meaningful for evaluating real retrieval quality

## Inference Runtime

Retrieval and embeddings are not the same as answer-generation.

For `AI Sage` and wisdom-profile synthesis, the backend can use a separate
inference model. The runtime is externalized via env:

| Variable | Purpose |
|----------|---------|
| `INFERENCE_LLM_PROVIDER` | Answer-generation provider selector. Current supported values: `openrouter`, `openai` |
| `INFERENCE_LLM_MODEL` | Model used for `/rag/query` and author wisdom synthesis |
| `INFERENCE_LLM_API_KEY` | Generic API key for the configured inference provider |
| `INFERENCE_LLM_BASE_URL` | Optional override for the provider base URL |
| `INFERENCE_LLM_HTTP_REFERER` | Optional OpenRouter referer header |
| `INFERENCE_LLM_APP_NAME` | Optional app name header, useful for OpenRouter |

If no inference provider/key is configured:

- `/rag/query` degrades to deterministic
  evidence summaries and wisdom profiles use template synthesis

Recommended current default:

```env
INFERENCE_LLM_PROVIDER=openrouter
INFERENCE_LLM_MODEL=openai/gpt-4o-mini
INFERENCE_LLM_API_KEY=your_openrouter_api_key
INFERENCE_LLM_BASE_URL=https://openrouter.ai/api/v1
INFERENCE_LLM_APP_NAME=CapitalOS
```

OpenRouter model naming examples:

- `anthropic/claude-sonnet-4.5`
- `openai/gpt-4o-mini`
- `google/gemini-2.5-pro`

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

### Validate before insert

For deterministic corpus reviews, fetch + parse + fanout can be previewed without
persisting any documents:

```bash
curl -X POST http://localhost:8000/rag/ingest/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source-uuid>"}'
```

The response includes one validation artifact per logical document with:

- proposed metadata
- included section headings
- extracted text length
- preview text
- deterministic quality metrics / rejection reason

Use this as the approval gate before `POST /rag/ingest/url`.

---

## Validation-first workflow for compendiums and curated corpora

The application should not infer corpus rules from hardcoded URLs or author
IDs. For compendiums, omnibus documents, or curated corpora, operators must
supply explicit `ingestion_config` and/or `selective_ingestion` rules at
registration time or update them on the source before ingestion.

Recommended operator flow:

```bash
# 1. Register a source with explicit fanout or selective rules when needed
curl -X POST http://localhost:8000/rag/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "author_id": "your_author_id",
    "url": "https://example.com/omnibus",
    "source_type": "html",
    "ingestion_config": {
      "mode": "fanout",
      "documents": [
        {
          "key": "doc-one",
          "title": "Document One",
          "canonical_work_id": "doc_one",
          "source_section": "Document One -> before Document Two",
          "selective_ingestion": {
            "start_after": "Document One",
            "stop_before": "Document Two"
          }
        }
      ]
    }
  }'

# 2. Validate before insert
curl -X POST http://localhost:8000/rag/ingest/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source-id>"}'

# 3. Only ingest after the validation artifacts look correct
curl -X POST http://localhost:8000/rag/ingest/url \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "<source-id>"}'
```

Validation artifacts should confirm:

- the included section headings are the ones you intended
- the extracted text is real body text, not heading-only noise
- per-document metadata looks correct before persistence
- low-quality or mis-bounded documents can be skipped before insert

If a source contains embedded subsection headings inside one parsed section, use
`ingestion_config.section_splits` to split that section generically before
fanout/selection. This keeps compendium handling source-agnostic and avoids
hardcoded URL-specific parsing rules.

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

### Source-link verification

Author Library is now source-first. When you inspect a document-detail payload, verify that it points back to the original source rather than serving stored reader content:

```bash
curl http://localhost:8000/rag/library/documents/<document-id> \
  -H "Authorization: Bearer $TOKEN"
```

For a correctly ingested source-backed document, verify:

1. `source_url` is present and opens the original source
2. `source_type`, `title`, and publication metadata are intact
3. `parent_document` and `child_documents` still provide navigation metadata when applicable

### Multimodal status for Issue 163

`voyage-multimodal-3.5` is **not adopted in this implementation**.

The codebase still embeds documents and queries with one active model family at a time, and this issue does not introduce:

- document routing between text and multimodal embedding spaces
- partitioned ANN retrieval by embedding-model family
- query-time dual routing across separate indexes

That means the shipped change improves parser fidelity and Author Library rendering without silently changing retrieval-space compatibility or the default `voyage-4` ingestion path.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAG_AUTHORS_CONFIG` | `config/rag_authors.yaml` | Path to author registry file |
| `RAG_EMBEDDING_MODEL` | `voyage-4` | Default embedding model for text-first documents |
| `RAG_MULTIMODAL_EMBEDDING_MODEL` | `voyage-multimodal-3.5` | Embedding model for multimodal documents |
| `RAG_EMBEDDING_PROVIDER` | `voyage` | Embedding provider selector |
| `RAG_EMBEDDING_MOCK` | `0` | Set to `1` to use deterministic mock embeddings (for tests/dev) |
| `VOYAGE_API_KEY` | — | Required for real Voyage embeddings; if absent, mock/dev fallback should be used |

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

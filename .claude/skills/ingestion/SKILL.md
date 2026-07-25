---
name: ingestion
description: The full author-ingestion workflow — config/rag_authors.yaml, sync-config, ingest-urls, selective-ingestion options, fanout, and the manual PDF-upload fallback. Use whenever asked to add an author or ingest a document/URL into the RAG corpus.
---

# Author ingestion, end to end

Real endpoint shapes below are taken directly from `api/app/routers/rag.py` —
if behavior seems to differ, that file is the source of truth, not this doc.

**Anything here that mutates the corpus goes through these app endpoints —
never through the read-only MCP connection (see the `corpus-inspect` skill)
or a direct `psql` write.**

## 1. Register/update an author — `config/rag_authors.yaml`

Fields per author: `id` (slug), `name`, `enabled`, `domains`,
`expertise_tags`, `overall_weight`, `role_type`, `photo_url` (and a few
optional metadata fields — see existing entries for the full set).

This file is **bind-mounted read-only** into the api container
(`./config:/app/config:ro` in `docker-compose.yml`) — edits are live
immediately, **no rebuild needed**. But editing the YAML alone does **not**
update the database — you still need step 2.

## 2. Sync config into the database

```
POST /rag/authors/sync-config
```
No body. Upserts every author in the YAML into `rag_authors`, idempotent —
safe to call repeatedly. Do this after any YAML edit (new author, changed
`photo_url`, changed weight, etc.) before expecting the change to show up
anywhere that reads from the DB (Author Library, Author Ingestion author
list). You can also create an author directly via `POST /rag/authors`
(id/name/enabled + optional advanced fields) without touching the YAML at
all — that's the path the Author Ingestion UI's "Create Author" form uses.

## 3. Register and ingest one or more URLs

```
POST /rag/authors/{author_id}/ingest-urls
{
  "urls": ["https://example.com/article"],
  "source_type": "html",              // html | pdf | text
  "selective_ingestion": null,        // optional, see below
  "ingestion_config": null            // optional, see fanout below
}
```
Registers each URL as a `rag_sources` row and kicks off background ingestion
(one URL at a time, in a background thread — the response returns
immediately with job IDs for polling, it doesn't block until done). Already-
registered URLs are re-queued rather than duplicated; URLs already
queued/running are skipped. Poll `GET /rag/ingest/activity?author_id=...` or
watch the `author-ingestion` realtime topic for status.

## 4. Selective ingestion (optional)

Limits which sections of an HTML/text source get ingested:
```json
{
  "start_after": "Introduction",       // begin after first heading containing this
  "stop_before": "Appendix",           // stop at first heading containing this
  "include_headings": ["Portfolio"],   // only include matching sections
  "exclude_sections": ["Disclaimer"]   // drop matching sections
}
```
Matching is case-insensitive substring. Leave all fields empty/omit entirely
to ingest the full source. Pass as `selective_ingestion` in the `ingest-urls`
body above.

## 5. Fanout (compendium / multi-document sources)

When one raw source (e.g. a collection of letters in one PDF) should become
multiple logical `rag_documents`, pass `ingestion_config`:
```json
{
  "mode": "fanout",
  "documents": [
    {
      "key": "essay-a",              // required, unique within this config
      "title": "Essay A",            // required
      "author_id": null,             // optional override of the source author
      "published_at": "2005-01-01",
      "collection": "Collected Essays",
      "work_type": "essay",
      "parent_key": null,            // logical-document parent/child linking
      "source_section": "Essay A",
      "selective_ingestion": { "include_headings": ["Essay A"] }
    }
  ]
}
```
**Preview before committing** — `POST /rag/fanout/preview` takes the same
`author_id` + `ingestion_config` (plus optional `source_title`/
`source_published_at`) and returns what documents *would* be created,
without ingesting anything. Use this to validate keys/parent links before
calling `ingest-urls` for real.

## 6. When the host blocks automatic fetching (403, bot detection)

If a source returns 403 or otherwise can't be fetched automatically (proven:
some hosts block on TLS fingerprint/behavior, not headers — spoofing a
browser User-Agent does not reliably help and isn't worth the reduced
transparency), there's a manual fallback:

```
POST /rag/ingest/pdf/upload   (multipart/form-data)
  author_id: <required>
  file: <PDF bytes, required>
  source_url: <optional — the original URL, stored for provenance only, never fetched>
  title: <optional, defaults to filename>
  published_at: <optional, YYYY-MM-DD>
  ingestion_config_json: <optional, same shape as ingestion_config above, JSON-encoded>
```
Download the PDF yourself (a browser can often reach what our server can't)
and upload the bytes directly — no HTTP fetch involved. If `source_url`
matches an existing source for that author (e.g. one that already failed
with a 403), the file attaches to that existing source instead of creating a
duplicate. The uploaded bytes are stored (`rag_sources.stored_file_bytes`)
so the document can be opened later via `GET /rag/sources/{id}/file` — this
only works for sources actually uploaded this way; URL-fetched sources never
have stored bytes (see `corpus-inspect`'s "sources missing a stored file"
query to find candidates for backfilling).

The Author Ingestion UI exposes this as **"Upload PDF instead"** (per-row,
only on already-failed sources) and **"Or upload a PDF directly"** (standalone
form, works any time, no pre-existing source needed).

## 7. Retry a failed source

```
POST /rag/ingest/retry/{source_id}
```
Re-runs ingestion for a previously failed/stalled source (must have a URL —
manual/uploaded sources with no URL use the PDF-upload flow instead, not retry).

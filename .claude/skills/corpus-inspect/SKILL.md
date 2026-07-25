---
name: corpus-inspect
description: Inspect the RAG/research corpus (authors, sources, documents, ingestion jobs) via the read-only Postgres MCP server instead of hand-writing docker exec psql commands. Use whenever asked about document counts, ingestion status, source ownership, or "did this config change take effect."
---

# Inspecting the RAG corpus

This repo has a read-only Postgres MCP server configured in `.mcp.json`
(`crystaldba/postgres-mcp`, `--access-mode=restricted`, pointed at the same
`capitalos-postgres` container `docker-compose.yml` runs). It exposes tools
like `execute_sql`, `list_objects`, `get_object_details` — use those directly
instead of constructing a `docker exec -i capitalos-postgres psql -c "..."`
command from scratch. Requires the stack to be up (`make up`) since the MCP
server joins the `capitalos_default` Docker network to reach Postgres.

**This connection is read-only by design, not by convention.** Restricted
mode validates and rejects any non-SELECT statement before it reaches the
database (confirmed: a `DELETE` against `rag_authors` was rejected with a
validation error, not executed). Never try to configure a writable one "for
convenience" — anything that mutates the corpus (registering sources, running
ingestion, deleting/reassigning ownership) goes through the app's own
endpoints (see the `ingestion` skill) or a tracked `migrations/NNN_*.sql`
file, never through this connection or a direct `psql` write.

## The tables that matter

- **`rag_authors`** — the author registry. `id` (slug), `name`, `enabled`,
  `domains`, `expertise_tags`, `overall_weight`, `role_type`. Source of truth
  is `config/rag_authors.yaml`, synced in via `POST /rag/authors/sync-config`
  (see the `ingestion` skill).
- **`rag_sources`** — one row per registered URL/upload. `author_id`, `url`
  (nullable — manually uploaded PDFs may have none), `source_type`
  (html/pdf/text/manual), `status` (pending/queued/running/ingested/failed),
  `user_id` (see ownership note below), `stored_file_bytes` (non-null only
  for sources ingested via the manual PDF-upload fallback — most sources
  don't have this).
- **`rag_documents`** — logical documents produced by ingesting a source. One
  source can fan out into multiple documents (compendium/fanout mode).
  `source_id`, `author_id` (can override the source's author for fanout
  cases), `title`, `published_at`/`publication_year`, `collection`,
  `work_type`, `parent_document_id` (for parent/child logical documents).
- **`rag_ingestion_jobs`** — one row per ingestion attempt against a source.
  `source_id`, `batch_id`, `status` (pending/queued/running/done/failed),
  `failure_category`, `error`, `stats_json` (per-logical-document outcomes
  for fanout jobs), `user_id`.
- **`realtime_events`** — the event log backing the live-updating ingestion
  UI. `topic` (`'author-ingestion'` for this domain), `event_name`
  (`source_queued`/`source_ingested`/`source_failed`/`batch_submitted`/etc.),
  `author_id`, `source_id`, `job_id`, `payload`.

## `user_id` ownership — read this before trusting a count

`rag_sources` and `rag_ingestion_jobs` are **owned per-user** via `user_id`.
This corpus was ingested under a mix of `user_id=1` (demo), `user_id=2`
(hitesh), and `NULL` at different points, which silently hid authors from
whichever account wasn't the one that ingested them, and produced wrong
document-count totals depending on which account was asking (see
`migrations/066_unify_rag_source_ownership.sql`). Everything was unified
under **`user_id=2`** — treat any row with a different (or NULL) `user_id` on
`rag_sources`/`rag_ingestion_jobs` as a sign that ownership drifted again,
not as expected variation. `rag_documents` and `rag_authors` themselves have
no `user_id` — ownership only lives on `rag_sources`/`rag_ingestion_jobs`,
and a document's effective owner is its source's `user_id`.

## Ready-made queries

**Author document counts (also catches ownership drift):**
```sql
SELECT a.name, count(d.id) AS doc_count,
       array_agg(DISTINCT s.user_id) AS owning_user_ids
FROM rag_authors a
LEFT JOIN rag_documents d ON d.author_id = a.id
LEFT JOIN rag_sources s ON s.id = d.source_id
GROUP BY a.name
ORDER BY doc_count DESC;
```
If `owning_user_ids` contains anything other than `{2}` (or `{NULL}` for
authors with zero documents), ownership has drifted for that author.

**Stuck/queued ingestion jobs:**
```sql
SELECT j.id, j.status, j.failure_category, s.url, s.author_id, j.created_at
FROM rag_ingestion_jobs j
JOIN rag_sources s ON s.id = j.source_id
WHERE j.status IN ('pending', 'queued', 'running')
ORDER BY j.created_at ASC;
```
A `running` job with no matching in-flight background thread (i.e. one from
more than a few minutes ago) is stuck, not actually running — see the
Research Overview "ingestion queue" bug this exact query would have caught.

**Sources missing a stored file that has a URL** (candidates for the
PDF-upload backfill flow — see `ingestion` skill):
```sql
SELECT id, author_id, url, status, source_type
FROM rag_sources
WHERE source_type = 'pdf'
  AND stored_file_bytes IS NULL
  AND url IS NOT NULL
ORDER BY created_at DESC;
```

**Recent ingestion activity for one author:**
```sql
SELECT event_name, status, source_id, job_id, created_at
FROM realtime_events
WHERE topic = 'author-ingestion' AND author_id = 'michael_mauboussin'
ORDER BY created_at DESC
LIMIT 20;
```

**Did a `rag_authors.yaml` config change actually take effect:**
```sql
SELECT id, name, domains, expertise_tags, overall_weight, role_type, updated_at
FROM rag_authors
WHERE id = 'howard_marks';
```
Compare `updated_at` against when `POST /rag/authors/sync-config` was called
— if it's stale, the sync didn't run (config edits are live in the file via
the bind mount, but DB-backed fields still need an explicit sync call).

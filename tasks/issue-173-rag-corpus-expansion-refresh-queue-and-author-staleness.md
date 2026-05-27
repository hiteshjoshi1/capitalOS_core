# Issue 173: RAG corpus expansion refresh queue and author staleness tracking

> **Depends on**: Issue 170 (entity/concept annotations) and Issue 171 (corpus-local expansion index).
> **Recommended order**: implement after Issue 172 retrieval wiring is merged (or in parallel),
> then deploy once 172 is live so freshness automation affects the active retrieval path.

## Problem

Issue 171 creates `rag_corpus_expansions`, but the expansion index is refreshed only when someone
manually runs:

```bash
python -m app.scripts.compute_corpus_expansions
```

That is not good enough once author ingestion is used regularly:

1. New articles for an existing author get entity/concept annotations, but the author's expansion
   terms remain stale until a manual recompute happens.
2. New authors can be ingested and annotated, but they will have zero expansion rows until a manual
   all-author compute runs.
3. Full recomputation is wasteful because one new Nick Sleep article should not require recomputing
   Buffett and Munger.
4. Retrieval diagnostics in Issue 172 could look worse than the actual corpus because the expansion
   index may lag behind the annotated chunks.

## Objective

Add deterministic staleness tracking and a refresh worker for corpus-local expansion rows:

- Ingestion marks the affected `author_id` as stale after chunk annotations are written.
- A refresh command recomputes `rag_corpus_expansions` only for stale authors.
- Refresh is idempotent, lock-protected, auditable, and safe to retry.
- The system never blocks ingestion on expensive expansion recomputation.
- Concurrency is race-safe: if ingestion marks an author stale during an in-flight refresh,
  the author remains stale and is picked up in the next refresh cycle.

## Architecture Decisions

- **Dirty-author state, not an append-only queue.** Use one row per author with current refresh
  status. Multiple ingestions for the same author coalesce into one pending refresh.
- **Do not recompute synchronously in ingestion.** Ingestion should remain fast and reliable.
  It only marks an author stale. The refresh command does the heavier NPMI work.
- **Author-scoped recompute.** Recompute only `--author-id <id>` for stale authors. This is the
  right unit because Issue 171 expansions are author-local.
- **Replace author rows atomically.** A successful refresh should replace that author's
  `rag_corpus_expansions` rows with the newly computed set. Plain UPSERT is not enough because
  old terms can remain after corpus changes.
- **Lock one author at a time.** Use Postgres row locks or advisory locks so two workers cannot
  recompute the same author concurrently.
- **Retryable failures.** A failed author refresh should record the error and leave the author
  stale for retry. It must not prevent other stale authors from refreshing.
- **Manual and automatable.** Provide a CLI command and Make target first. A scheduler/background
  runner can call the same command later.
- **Versioned staleness watermark.** Use monotonically increasing `stale_version` and
  `refreshed_version` to prevent the classic race where refresh marks `is_stale=false` after a
  newer ingestion already marked the author stale again.
- **Claim lease for crash safety.** Refresh workers claim authors with a lease
  (`in_progress=true`, `claim_token`, `claim_expires_at`). Expired leases are reclaimable.

## Proposed Schema

Migration: `migrations/055_corpus_expansion_refresh_state.sql`

```sql
CREATE TABLE rag_corpus_expansion_refresh_state (
  author_id       TEXT PRIMARY KEY REFERENCES rag_authors(id) ON DELETE CASCADE,
  is_stale        BOOLEAN NOT NULL DEFAULT TRUE,
  stale_version   BIGINT NOT NULL DEFAULT 0,
  refreshed_version BIGINT NOT NULL DEFAULT 0,
  stale_reason    TEXT,
  stale_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  in_progress     BOOLEAN NOT NULL DEFAULT FALSE,
  claim_token     UUID,
  claim_started_at TIMESTAMPTZ,
  claim_expires_at TIMESTAMPTZ,
  last_attempted_at TIMESTAMPTZ,
  last_success_at   TIMESTAMPTZ,
  last_error      TEXT,
  refresh_count   INT NOT NULL DEFAULT 0,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX rag_corpus_expansion_refresh_state_stale_idx
  ON rag_corpus_expansion_refresh_state(is_stale, in_progress, stale_at);

CREATE INDEX rag_corpus_expansion_refresh_state_lease_idx
  ON rag_corpus_expansion_refresh_state(in_progress, claim_expires_at);
```

Optional but useful if implementation cost is low:

```sql
CREATE TABLE rag_corpus_expansion_refresh_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  author_id       TEXT NOT NULL REFERENCES rag_authors(id) ON DELETE CASCADE,
  status          TEXT NOT NULL CHECK (status IN ('running','success','failed','skipped')),
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  rows_written    INT,
  pivots_computed INT,
  error           TEXT
);
```

The run table is audit history. The state table is the operational source of truth.

## Ingestion Hook

After a document's chunks are persisted and entity/concept extraction has completed, mark the
author stale:

```sql
INSERT INTO rag_corpus_expansion_refresh_state (author_id, is_stale, stale_reason, stale_at, updated_at)
VALUES (:author_id, TRUE, :reason, now(), now())
ON CONFLICT (author_id) DO UPDATE SET
  is_stale = TRUE,
  stale_version = rag_corpus_expansion_refresh_state.stale_version + 1,
  stale_reason = EXCLUDED.stale_reason,
  stale_at = now(),
  updated_at = now();
```

Rules:

- If `author_id` is missing, skip and log a warning.
- Mark stale once per ingestion job, not once per chunk.
- Do not fail ingestion if staleness marking fails; log a warning.
- Staleness marking should not clear `in_progress`; refresh workers own lease lifecycle.
- Reason examples:
  - `document_ingested`
  - `document_reingested`
  - `entity_concept_backfill`
  - `registry_version_changed`

## Refresh Command

Add:

```bash
python -m app.scripts.refresh_stale_corpus_expansions
```

Flags:

| Flag | Default | Effect |
|---|---|---|
| `--author-id ID` | all stale authors | Refresh one author even if not stale, unless `--stale-only` is set |
| `--limit N` | 10 | Max stale authors to process in one run |
| `--stale-only` | false | Skip author if not stale |
| `--dry-run` | false | Print authors that would be refreshed without writing |
| `--min-support N` | 3 | Passed through to `compute_corpus_expansions` |
| `--min-npmi F` | 0.10 | Passed through to `compute_corpus_expansions` |
| `--top-n N` | 30 | Passed through to `compute_corpus_expansions` |
| `--lease-seconds N` | 900 | Lease duration for claimed authors |

Expected output:

```text
[refresh] author=nick_sleep status=running reason=document_ingested
[refresh] author=nick_sleep status=success pivots=25 rows_written=587
[refresh] DONE refreshed=1 failed=0 skipped=0
```

Selection/claim semantics (required):

1. Select stale candidates ordered by `stale_at ASC`.
2. Claim rows in SQL using `FOR UPDATE SKIP LOCKED` and set
  `in_progress=TRUE`, `claim_token=<uuid>`, `claim_started_at=now()`,
  `claim_expires_at=now() + interval ':lease_seconds seconds'`.
3. Reclaim rows whose `claim_expires_at < now()` (stuck workers).
4. Process each claimed author independently so one failure does not block others.

## Compute Behavior Change

Issue 171's compute script currently UPSERTs rows. For refresh correctness, add or expose an
author-scoped replace mode:

1. Compute the author's full current expansion set.
2. In one transaction:
   - delete `rag_corpus_expansions WHERE author_id = :author_id`
   - insert the computed rows
  - mark refresh state success only for the claimed row:
    - `last_success_at=now()`, `last_error=NULL`, `refresh_count=refresh_count+1`
    - `refreshed_version=:claimed_stale_version`
    - `in_progress=FALSE`, `claim_token=NULL`, `claim_started_at=NULL`, `claim_expires_at=NULL`
    - `is_stale = CASE WHEN stale_version > :claimed_stale_version THEN TRUE ELSE FALSE END`
3. If computation fails, do not delete existing expansion rows.

This avoids stale terms surviving forever after documents are removed, aliases are deactivated,
or support falls below threshold.

Failure behavior for a claimed author:

- Record `last_error`, `last_attempted_at=now()`, clear claim fields, set `in_progress=FALSE`.
- Keep `is_stale=TRUE` so retries are possible.
- Never leave claim fields populated after command exits (success or failure).

## Make Targets

Add:

```make
rag-expansions-refresh:
	docker compose exec -T api python -m app.scripts.refresh_stale_corpus_expansions

rag-expansions-refresh-author:
	docker compose exec -T api python -m app.scripts.refresh_stale_corpus_expansions --author-id $(AUTHOR_ID)
```

Usage:

```bash
make rag-expansions-refresh
make rag-expansions-refresh-author AUTHOR_ID=nick_sleep
```

## Acceptance Criteria

- [ ] Migration `055_corpus_expansion_refresh_state.sql` applies cleanly.
- [ ] Ingestion marks the affected author stale after successful chunk persistence and annotation.
- [ ] Staleness marking is job-scoped, not per chunk.
- [ ] Ingestion does not fail if staleness marking fails.
- [ ] Issue ordering is explicit: 173 can be implemented in parallel but should be deployed after
  Issue 172 retrieval wiring is live.
- [ ] `refresh_stale_corpus_expansions` processes only stale authors by default.
- [ ] `refresh_stale_corpus_expansions --author-id nick_sleep` refreshes only Nick Sleep.
- [ ] `--dry-run` prints candidate authors and writes no rows.
- [ ] Successful refresh marks `is_stale=false`, sets `last_success_at`, clears `last_error`,
  increments `refresh_count`, and writes expansion rows.
- [ ] Failed refresh records `last_error`, keeps `is_stale=true`, and does not delete existing
  expansion rows.
- [ ] Author-scoped refresh replaces old rows atomically; stale expansion rows for deleted or
  no-longer-supported terms do not survive a successful refresh.
- [ ] Concurrent workers cannot refresh the same author at the same time.
- [ ] If ingestion marks an author stale while refresh is running, the final state remains
  `is_stale=true` unless the refresh processed the newest `stale_version`.
- [ ] Stuck claims are recoverable: expired leases can be reclaimed in a later run.
- [ ] Make targets exist for all-stale and single-author refresh.
- [ ] Existing deterministic gates pass: backend tests, API smoke, frontend tests if touched.

## Tests

- [ ] Unit test: `mark_author_expansions_stale(author_id, reason)` inserts a new stale row.
- [ ] Unit test: repeated staleness marks for same author coalesce into one state row.
- [ ] Unit test: ingestion hook calls staleness marking once per document/job.
- [ ] Unit test: refresh command selects only stale authors by default.
- [ ] Unit test: `--author-id` limits refresh to exactly one author.
- [ ] Unit test: dry-run does not mutate state or expansion rows.
- [ ] Unit test: successful refresh clears stale flag and records metrics.
- [ ] Unit test: failed refresh keeps stale flag and preserves prior expansion rows.
- [ ] Unit test: author-scoped replace deletes old rows only after new rows have been computed.
- [ ] Unit test: stale-version race safety — refresh claims version N, ingestion bumps to N+1,
  refresh completion keeps `is_stale=true`.
- [ ] Unit test: expired lease recovery — worker A crashes after claim; worker B reclaims row
  after lease expiry and completes refresh.
- [ ] Integration test: ingest a new document for an existing author, confirm author becomes stale,
  run refresh, confirm author becomes fresh and expansion rows exist.

## Task Checklist

- [ ] Add migration `migrations/055_corpus_expansion_refresh_state.sql`.
- [ ] Add helper module for marking author expansion state stale.
- [ ] Wire staleness marking into ingestion after successful chunk persistence/annotation.
- [ ] Refactor or extend `compute_corpus_expansions` to support author-scoped atomic replace.
- [ ] Implement `api/app/scripts/refresh_stale_corpus_expansions.py`.
- [ ] Add Make targets for refresh commands.
- [ ] Add tests listed above.
- [ ] Add command-level lease claim/release logic (`FOR UPDATE SKIP LOCKED` + expiry reclaim).
- [ ] Run targeted backend tests.
- [ ] Run `make test-backend`.
- [ ] Run `make api-smoke`.
- [ ] Verify semantic intent: after ingesting or simulating new author content, stale state is
  created and refresh updates only that author.

<!-- IMMUTABLE_PLAN_END -->

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `prepare`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: No workflow outcome recorded yet.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- retry_gate_pending: `no`

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-173-rag-corpus-expansion-refresh-queue-and-author-staleness` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->

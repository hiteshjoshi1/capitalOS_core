# Issue 132: Uploads: store under a fixed name per job, reject path traversal, cap upload size

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/132

## Objective
- An uploaded statement is always stored inside its own job folder, whatever filename the client sends.
- Uploads have a configurable size cap with a clear 413, and are never buffered whole in memory.

## Architecture Decisions
- Stored name is fixed: `data/raw/<job_id>/upload<ext>`, where `<ext>` is the lowercased extension of the
  original name if it is on an allow-list (`.csv .xls .xlsx .tsv .txt`), else no extension. Format detection
  and the xls/xlsx parsers key on the stored path's extension (case-insensitively), so they keep working.
  `original_filename` is kept unchanged as metadata (job list, report, dashboard).
- `realpath` containment check before the copy; failure raises instead of writing.
- Size cap: `INGEST_MAX_UPLOAD_MB` (default 25). Two layers: an ASGI middleware refuses `POST /ingest/*` whose
  Content-Length exceeds cap + 64 KB multipart allowance before the body is read; the handler copies the file
  to a temp file in 1 MB chunks and stops with 413 once the cap is passed (covers chunked bodies).
- `GET /ingest/jobs/{id}` still returns `stored_path` / `report_path` (additive-only rule). They are server
  paths, but no longer echo client input; the UI does not use them.

## Acceptance Criteria
- [x] A filename of `../../x.csv` or an absolute path is stored inside the job folder, test proves it.
- [x] Oversized upload is rejected with 413, test proves it.
- [x] Existing upload flows (all parsers) still work.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_ingest_upload_safety.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `tests`: pass — `tests/test_ingest_upload_safety.py` + ingest suites: 23 passed
- `make verify`: pass — backend 490 passed, frontend 284 passed, lint + typecheck clean

## Extra Files Changed
- `.env.example`, `docs/setup/api-keys.md` — document `INGEST_MAX_UPLOAD_MB` and always setting `AUTH_ACCESS_TOKEN_SECRET`.
- `api/app/main.py` — register the upload size middleware.

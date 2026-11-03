# Issue 141: Holdings uploads dated by the statement's as-of date, not the upload day

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/141

## Objective
- An uploaded holdings (or balance) statement is dated by the day it describes, so an older file lands on its own date instead of replacing today's snapshot.
- The date's source is recorded and shown, and "today" means today in the app timezone.

## Architecture Decisions
- Date precedence: **file > user > fallback**. The file's stated date (parser_meta `statement_period_end` / `report_date` / `statement_date` / `as_of`, or a dated balance row) wins; else the `as_of` sent with the upload; else today in the app timezone. The UI always sends a date (today unless changed), so letting the user's date win would re-date correctly dated statements to the upload day. When the user's date differs from the file's, the result carries an `as_of_note` saying so.
- Holdings parsers (Sharekhan, DBS Vickers) read a *labelled* date ("as on/of/at", "statement/report/valuation/holding date", or a cell starting with "Date") from the rows above the holdings header (Excel) or from the export's text (HTML). Unlabelled dates are ignored (purchase dates, client DOB-like values). Numeric dates are read day-first (India/Singapore exports).
- IBKR activity CSV: `Statement,Data,Period,"<start> - <end>"` → `statement_period_end`.
- One helper, `app/core/clock.py::app_today()` (TZ env, default Asia/Singapore; same default as the dashboard/schedulers). No existing shared helper was found; the other ad-hoc `ZoneInfo(os.getenv("TZ", ...))` sites are left as they are.
- No migration: the date and its source go in existing `metadata_json` (broker_import_runs for holdings, account_balance_snapshots for balances) and in `canonical_result` of the upload report (`as_of_date`, `as_of_source`, `user_as_of`, `as_of_note`; additive).
- `mark_rollups_dirty` already used the resolved report date; it now gets the file/user date instead of today.

## Acceptance Criteria
- [x] Uploading an older holdings file creates a snapshot on its own date and leaves today's intact (test).
- [x] User-supplied `as_of` dates a file that has none; file date beats user date (tests).
- [x] Date source recorded (import-run / balance-snapshot metadata) and shown in the upload result (UI pill).
- [x] One timezone-aware today helper (test).
- [x] History invalidation from the resolved date (test).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_upload_as_of.py -q`
- `cd web && npx vitest run src/__tests__/Ingest.test.tsx`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify` (ruff, eslint, pinned refs)
- `typecheck`: pass — mypy (106 files), tsc
- `tests`: pass — backend 602 passed; frontend 45 files / 299 tests passed
- `api-smoke`: pass — isolated worktree Postgres: both adapters write `metadata_json` (jsonb cast, ON CONFLICT update) as expected; instance dropped afterwards
- `policy-checks`: pass — synthetic fixtures only

## Extra Files Changed (Codex Mutable)
- `api/app/ingestion/parsers/ibkr_activity_csv_v1.py` — reason: cheap fix of the same fallback for IBKR activity statements (period end).
- `api/app/ingestion/runner.py` — reason: pass the user's `as_of` from `run_ingestion` to the adapters (signature only; no change to dedup or failure paths).

## Human Action Summary (Codex Mutable)
- Bank/card parsers: UOB account and DBS account already state a date; OCBC account CSV states none (now dated by the user's `as_of`, default today); card parsers write no balance snapshot (transactions carry their own dates).
- Real exports were not inspected: if a real Sharekhan/DBS Vickers export phrases its date differently from the labels above, the upload falls back to the user's date (and says so in the result); add the label to `app/ingestion/as_of.py::_LABEL`.

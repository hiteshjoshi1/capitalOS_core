# Issue 359: Database: drop dead and legacy tables

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/359 (from #353 T2, #130 §1.9)

## Objective
- Remove the tables and columns nothing reads any more, so readers can't pick the wrong copy.
- No change to any number the app shows.

## Architecture Decisions
- One migration (085) with a guard: it raises if any dropped table holds a row, or an `event_group_id` is set (D-98).
- Kept: `broker_accounts.legacy_account_id` (the account link every read joins on) and
  `broker_import_runs.legacy_account_id` (read by the Flex scheduler/rebuild, returned by the portfolio API).
- `crypto_networth_updated` stays in the ownership reassign result (fields are only added), always 0.

## Acceptance Criteria
- [x] Dropped: `positions` (+ 057 triggers/function), `asset_identifiers`, `portfolio_event_groups`
  (+ `event_group_id` on trades, cash ledger, corporate actions), `wallet_accounts`, `raw_files`,
  `ingestion_jobs`, `crypto_user_networth`, `legacy_account_id` on the position / cash-balance / NAV snapshots.
- [x] Last readers removed: `app/portfolio/legacy_backfill.py`, `app/portfolio/parity_report.py`,
  the positions branch of `market_data.held_asset_ids`, the networth count/update in `services/ownership.py`.
- [x] Parity on a restored copy of the real data (backup 2026-11-10 22:40): 31 API responses identical before and after.

## How To Test
- `make db-schema-check`, `make verify`.
- `scripts/db-table-usage.py`: only transfer_links, portfolio_report_metrics, portfolio_fx_rates remain listed.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal
- 2026-11-10: real DB had 0 rows in every dropped table and 0 set `event_group_id`s; the snapshot
  `legacy_account_id` columns were written on insert but never read (all reads join `broker_accounts`).

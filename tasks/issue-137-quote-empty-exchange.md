# Issue 137: Quote scheduler re-runs all day when a configured exchange has no symbols

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/137

## Objective
- A close window whose exchanges include one with no active symbols (default `STOCK_EXCHANGES=US,SGX,HKEX,NSE`) runs once per day, not every retry interval.

## Architecture Decisions
- `run_exchange_refresh` records a run for an exchange with no active symbols: a `market_data_runs` row with provider `none`, status `success`, 0 requested/upserted, `finished_at` set (`EMPTY_EXCHANGE_PROVIDER`). The scheduler's done-check (`_latest_success_for_exchanges`) is unchanged and now sees a success row for every exchange in the window.
- Rejected: leaving empty exchanges out of the done-check. The symbol-map backfill (`_backfill_symbol_map_for_exchange`) only runs inside the refresh, so a window whose exchanges all looked empty would never be due again and a newly held stock there would never get a symbol-map row or a quote. It would also leave `/market-data/status` showing an old run for an exchange that has since emptied.
- `/market-data/runs` and `/market-data/status` show the 0-symbol run as it is ("none", success, 0 → 0): the exchange was checked and had nothing to fetch. The Data Hub "Recent activity" feed skips provider `none` runs, so they don't say "Refreshed SGX market data" or push real imports/refreshes out of the feed.
- The deferred-symbols case (daily limit, not full coverage) is unchanged: no row, as before.

## Acceptance Criteria
- [x] With one configured exchange empty, the window runs once per day (test, real done-check against `market_data_runs`).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_market_data.py tests/test_dashboard.py -q`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass — test_market_data.py + test_dashboard.py; the new scheduler test fails on main's service.py (no SGX run row).
- `make verify`: see PR.

## Extra Files Changed (Codex Mutable)
- `api/app/routers/dashboard.py` — reason: keep 0-symbol runs out of the Data Hub activity feed.

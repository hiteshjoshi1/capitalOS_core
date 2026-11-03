# Issue 139: FX: local rate table; a missing rate is partial, never 1.0; tests use real-looking rates

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/139

## Objective
- Valuations convert currencies from a local, dated rate table instead of asking a provider on every request, so pages still load when the FX providers are down.
- A currency with no rate is never counted 1:1: it is left out of totals and the response (and UI) says so.
- One written rule for which date's rate applies: balances at their anchor date, flows at their own transaction date.

## Architecture Decisions
- `fx_rates(rate_date, base, quote, rate, source, fetched_at)`, unique `(rate_date, base, quote)` (migration 070). A row means 1 `base` = `rate` `quote` (the providers' own convention). Frankfurter rows are EUR-based, open.er-api rows USD-based; any pair is derived through a shared base on the same date. IBKR's `portfolio_fx_rates` (1 from = rate to) is read alongside as source `ibkr`.
- Readers take the latest row on or before the date. Within `FX_LOOKBACK_DAYS` (7) it is current; older (up to `FX_STALE_MAX_DAYS`, 366) it is used and the currency is reported stale; nothing at all means missing (left out, never 1.0). Base to base is 1.0.
- Provider calls happen only when the store has nothing current for a date (or, for the last 7 days, its newest row is more than 3 days old): one Frankfurter call per date range for every currency; open.er-api (latest-only) only for today, stored under its own date. Success is cached 24 h in-process, failure 60 s. If storing fails, the fetched rows are still used. Then `FX_FALLBACK_RATES`.
- Daily fill: a sleep-proof due check (D-19 / #112 pattern) in the market-data scheduler, 16:30 Europe/Berlin (`FX_DAILY_FILL`), after the ECB publishes.
- Per-request FX notes (contextvar, `FxNotesMiddleware`) feed additive response fields `fx_incomplete`, `fx_missing_currencies`, `fx_stale_currencies`; a request with missing/stale FX stays out of the shared valuation cache (`mark_degraded`, #147).
- FX-date rule: balances at the anchor date (dashboard, crypto current vs prior-month snapshot vs each trend month), flows at their own date (dividend payments; one batched store read per range). Spending and the dashboard cash flow still use the 1st of the month: follow-up.

## Acceptance Criteria
- [x] Provider down: pages still load using stored rates, flagged if stale (test).
- [x] An unknown currency is flagged, not counted 1:1 (test).
- [x] Tests use realistic, non-1 synthetic rates; no test reaches a real provider.
- [x] Crypto summary and dividend history follow the FX-date rule (tests).

## How To Test
- `make verify` (lint, typecheck, backend + frontend tests).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_fx.py -q`.
- Isolated stack: `make up && make db-migrate` applies 070; `fx.get_rates` against Postgres stores, reads back, upserts.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify` (ruff, eslint, pinned refs)
- `typecheck`: pass — mypy (101 files), tsc
- `tests`: pass — backend 514 passed, frontend 288 passed
- `api-smoke`: pass — isolated Postgres: migration 070 applied; store, read-back, upsert and `fill_daily` exercised with fake providers
- `policy-checks`: pass

## Extra Files Changed (Codex Mutable)
- `api/app/portfolio/legacy_backfill.py` — reason: it also defaulted a missing rate to 1.0; now skips the row with a data-quality event.
- `api/app/routers/spending.py` — reason: `.get(cur, 1.0)` call sites now exclude (0.0) and flag.
- `api/app/valuation_cache.py` — reason: docstrings, and the new FX env vars in the result stamp.

## Human Action Summary (Codex Mutable)
- Next expected action: review; merge after #161 and #165; `make deploy` applies migration 070.
- Open questions:
  - Spending / dashboard cash flow still convert at the 1st of the month (flows rule says transaction date). Follow-up issue?

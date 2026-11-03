# Issue 147: Slow pages: stop recomputing valuation on every request

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/147

Stacked on #161 (`feature/issue-133-current-month-compare`), which added the
`_cached_networth_components` per-request memo for /summary.

## Objective
- Pages that show valuations (Wealth Overview, Stocks, Cash, Dividends) stop
  recomputing the same net worth / exposure / holdings over and over, within a
  request and across requests while the data hasn't changed.
- Responses stay exactly the same.

## Architecture Decisions
- **One decorator, two layers** (`api/app/valuation_cache.py`): `valuation_cached`
  memoises a `(db, ...)` helper per request (a `RequestScope` set by a pure ASGI
  middleware for GET/HEAD through a contextvar, like the request id), and with
  `shared=True` also in a bounded in-process LRU (256 entries, 10 min TTL).
  Outside a GET request (schedulers, scripts, writes) nothing is cached.
- **Shared entries are valid only for the same data watermark, day and
  settings.** Watermark = in-process write generation (bumped before and after
  any commit of a transaction that wrote, via SQLAlchemy engine/session events)
  + on Postgres `pg_current_wal_insert_lsn()`, which moves on any committed write
  by anyone (psql, restores, scripts in other containers). Read once per request
  before its first cached computation. Day = UTC and app-local date. Settings =
  env vars that change results (SNAPSHOT_DAY, TZ, ownership scope, FX settings…).
- **Never another user's data**: shared caching refuses a helper without
  `current_user_id` (TypeError at import), and the key always carries it.
- **Live views**: helpers that only use an anchor through its date are keyed by
  (anchor date, FX date), so a live "now" anchor reuses the value computed earlier
  that day. The one time-exact part of net worth, credit-card liabilities
  (transactions before the exact anchor), was split out of
  `_networth_components` and is computed per request. The request's "now"
  (`_current_anchor_ts`) is frozen for the length of the request.
- **Not shared**: `latest_wallet_valuation` (its stale flags are relative to the
  current time), `_platform_allocation` (returns the exact anchor), prices maps
  (not user data; per request only).
- **FX** (`api/app/fx.py`): rates cached per (date, base, currency); each
  provider is asked once per (date, base) for all its currencies; failures and
  empty answers are cached for 60 s (`FX_NEGATIVE_CACHE_SECONDS`). Source order
  per currency is unchanged (Frankfurter, EUR cross, open.er-api, env fallback,
  else 1.0). A 1.0 default marks the request degraded, and nothing computed after
  it is shared.
- **Batched reads**: expected dividends (trades, yield snapshots and prices: one
  query each for all holdings; Postgres uses LATERAL … LIMIT 1, SQLite
  ROW_NUMBER()), dividend market values, cash-trend stablecoins (2 queries for 6
  months), data-hub market freshness (1 query instead of 4 per exchange).
- **Concurrent requests** computing the same shared value (Wealth Overview's
  parallel /bootstrap + /summary) compute it once: per-key lock, 30 s timeout.

## Acceptance Criteria
- [x] Per-request memoisation across the heavy helpers (net worth, stock exposure,
      top holdings, geography, cash, canonical loaders).
- [x] FX cached per (date, base, currency); ≤ 1 provider call per date per base;
      provider failures negative-cached; fallback semantics unchanged.
- [x] Dividends expected overview and cash trend N+1 batched (SQLite-compatible).
- [x] Cross-request cache keyed by user/helper/params + data watermark, TTL and
      size bound; never serves another user's data; correct for live endpoints.
- [x] Data-hub market part uses cheap counts.
- [x] Responses identical with and without caches (tests + Postgres A/B on demo data).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_valuation_cache.py -q`
- `make verify`
- On an isolated stack with demo data (`make up db-migrate db-seed-demo`): load
  Wealth Overview twice; the second load's API calls take ~10-35 ms.
- `VALUATION_CACHE_ENABLED=0` turns the cache off (for comparisons).

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results
- `make verify` (lint, typecheck, backend + frontend tests): see PR.
- Postgres A/B (old code on :8001 vs new on :8000, same demo DB, interleaved):
  all 12 measured endpoints return identical JSON (old vs new cold vs new warm).

## Extra Files Changed
- `api/app/market_data/service.py` — reason: cheap freshness counts for data hub.
- `api/app/portfolio/canonical_reads.py`, `api/app/portfolio/ibkr_flex.py`,
  `api/app/crypto/valuation.py` — reason: the shared loaders are cached where defined.
- `api/tests/conftest.py` — reason: each test starts with an empty shared cache.

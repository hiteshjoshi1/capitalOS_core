# Stock Price Refresh PRD

## Goal
- Refresh stock/fund prices daily so dashboard net worth is not stale.
- Run per-exchange staggered jobs for better end-of-day alignment.
- Work on free tiers with per-day symbol caps (default `20` per exchange per run).
- Use provider chain with automatic fallback:
  - US: `finnhub -> eodhd -> yahoo`
  - Non-US: `eodhd -> eoddata -> yahoo`
- Keep response payloads ephemeral (do not store raw provider payloads).

## Architecture Decisions
- Introduce `MarketDataProvider` abstraction with provider-specific implementations.
- Use a refresh service that:
  - builds active symbol lists by exchange and orders by staleness (oldest/missing first),
  - applies `STOCK_DAILY_SYMBOL_LIMIT` before fetch (default `20`),
  - fetches via provider chain with automatic fallbacks,
  - upserts into `prices`,
  - records run-level + symbol-level audit logs.
- Introduce staggered scheduler jobs per exchange, driven by env-configured local times.
- Update dashboard valuation logic to use latest available EOD prices for STOCK/FUND where available, fallback to `cost_basis_base` if missing.

## Provider Plan (Free Tier)
- `EODHD`: used as per-symbol EOD fetch (`/api/eod/{symbol}`), not bulk endpoint.
- `Finnhub`: US-only primary when `FINNHUB_API_KEY` is configured.
- `EODData`: non-US secondary fallback via `Quote/Get/{exchange}/{symbol}` when `EODDATA_API_KEY` is configured.
- `Yahoo`: fallback only; request pacing controlled by:
  - `YAHOO_BATCH_SIZE` (default `1`)
  - `YAHOO_SLEEP_MS` (default `750`)
  - `YAHOO_MAX_ATTEMPTS` (default `1`)
- Daily cap:
  - `STOCK_DAILY_SYMBOL_LIMIT` (default `20`) per exchange run.

### Current Coverage Notes (as tested)
- US symbols: EODHD per-symbol works with current key.
- HKEX symbols: partial success on EODHD (e.g., `700.HK`, `1698.HK`).
- SGX/NSE symbols: current EODHD access returns `Ticker Not Found` for tested symbols, so these rely on fallback provider.
- Yahoo endpoint may return `429` under unofficial rate limits; treat as best-effort fallback, not guaranteed SLA.

## DB Changes
1. New table: `market_symbol_map`
- Canonical symbol ownership and exchange membership.
- `exchange_symbol` is source of truth.
- Provider-specific override fields only for exceptions.

2. New table: `market_data_runs`
- One row per execution (provider + exchange + trade_date).
- Captures counts, status, timing, and summary errors.

3. New table: `market_data_run_items`
- Symbol-level result logs for observability and debugging.

4. Alter table: `prices`
- Add `trade_date`, `exchange_code`, `provider_symbol`, and ensure `source` exists.
- Add unique index for idempotent EOD upsert by `(asset_id, trade_date, source)`.

### Sample rows
- `market_symbol_map`
  - asset_id=42, exchange_code='NSE', exchange_symbol='RELIANCE', quote_currency='INR', eodhd_symbol_override='RELIANCE.NSE', yahoo_symbol_override='RELIANCE.NS'
- `market_data_runs`
  - provider='eodhd', exchange_code='NSE', trade_date='2026-03-04', status='partial', requested_symbols=27, received_rows=26
- `market_data_run_items`
  - run_id=9001, asset_id=42, provider='yahoo', symbol='RELIANCE.NS', status='fallback_upserted', price=2941.25

## API Routes
- `GET /market-data/status`
  - Returns latest run per exchange, plus coverage metrics.
- `GET /market-data/runs?limit=N`
  - Returns recent run history.
- `POST /market-data/refresh-now`
  - Triggers immediate refresh (all exchanges, staggered=false), admin-key protected.

## Frontend Components
- Add `Market Data` route/page (`/market-data`) showing:
  - latest run status by exchange,
  - recent run history,
  - manual refresh button.
- Add navigation link from dashboard/pill row.

## Test Plan
Backend:
- Unit test provider parsing/mapping for both providers.
- Router tests for status and refresh endpoints.
- Dashboard test verifying STOCK/FUND valuation uses `prices` when available and falls back otherwise.

Frontend:
- Component test for market data page rendering status/error states.

E2E (Playwright):
- Happy-path navigation test: Dashboard -> Market Data page loads and title is visible.

Verification commands:
- `make lint`
- `make typecheck`
- `make test-backend`
- `make test-frontend`
- `make e2e`

## Manual Verification Runbook
1. Apply DB changes
- Run: `make db-migrate`
- Confirm migration applied (example): `docker compose exec postgres psql -U capitalos -d capitalos -c "\dt market_data_runs"`
2. Start services
- Run: `make up`
- Health check: `curl http://localhost:8000/health`

3. Trigger a refresh manually
- If `STOCK_ADMIN_KEY` is set:
  - `curl -X POST http://localhost:8000/market-data/refresh-now -H "x-admin-key: <YOUR_KEY>"`
- If key is not set in local dev, set it in `.env`, restart API, then call again.
- Required keys for best coverage:
  - `EODHD_API_KEY` (recommended for US + non-US EOD)
  - `FINNHUB_API_KEY` (US primary, optional but recommended)
  - `EODDATA_API_KEY` (non-US secondary fallback)

4. Verify run status via API
- `curl http://localhost:8000/market-data/status`
- `curl "http://localhost:8000/market-data/runs?limit=10"`
- Expect per-exchange rows with `status` in `success` or `partial`, and non-zero `requested_symbols` for exchanges with mapped assets.

5. Verify rows written in DB
- Check latest prices by source:
  - `docker compose exec postgres psql -U capitalos -d capitalos -c "select source, exchange_code, trade_date, count(*) from prices where trade_date is not null group by 1,2,3 order by trade_date desc, exchange_code;"`
- Check symbol-level run logs:
  - `docker compose exec postgres psql -U capitalos -d capitalos -c "select run_id, symbol, provider, status, price, trade_date from market_data_run_items order by id desc limit 30;"`

6. Verify dashboard valuation uses fresh prices
- API check (before/after refresh):
  - `curl "http://localhost:8000/dashboard/summary?month=2026-03" | jq`
- For a stock you hold, compare expected value:
  - expected `holding_value_base ~= quantity * latest_price`
- Confirm totals changed if price changed versus prior snapshot/cost basis fallback.

7. Verify in UI
- Open `http://localhost:5173`
- Check Dashboard net worth/holdings cards reflect new stock values.
- Open `http://localhost:5173/market-data`
- Confirm latest run per exchange and recent runs are visible.

8. Failure-path checks
- Temporarily break EODHD key and run refresh.
- Confirm fallback provider appears in `market_data_run_items.provider` for missing symbols and run status becomes `partial` (not silent failure).

9. Symbol override checks (important for non-US)
- If provider returns `404` for a symbol, set explicit overrides:
  - `eodhd_symbol_override` and/or `yahoo_symbol_override` in `market_symbol_map`
- Example:
  - `update market_symbol_map set eodhd_symbol_override='RELIANCE.NSE' where exchange_code='NSE' and exchange_symbol='RELIANCE';`

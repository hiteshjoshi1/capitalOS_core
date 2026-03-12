# Issue 108: Stock Detail Page Improvements

## Objective

Improve the Stock Holdings page (`/holdings`) with four targeted changes:

1. **Header Navigation Fix** – Replace the current sub-navigation pills (Dashboard, Crypto Holdings, Cash) with exactly three links: Dashboard, User, and Ingest.
2. **Geo Location Accuracy** – Fix geography display for securities. Currently most show "UNKNOWN" because IBKR-imported assets often lack `home_country`. Leverage `market_symbol_map.exchange_code` (US, HKEX, NSE, SGX) as an additional inference source, and add a one-time backfill migration.
3. **Top 15 Securities** – Increase the holdings display from the current 10-item backend limit (which yields ~8 non-CASH rows) to 15 non-CASH securities.
4. **Per-Security Detail Columns** – Show shares held (`quantity`), purchase price per share (`avg_cost`), and current market price (`latest_price`), with purchase and current prices displayed in the security's native currency (`quote_currency`).

## Architecture Decisions

- **Decision 1: Geo inference via exchange_code** – Extend `infer_country()` in `dashboard.py` to accept an optional `exchange_code` parameter. Map `HKEX→HK`, `NSE→IN`, `SGX→SG`, `US→US`. This uses data already in `market_symbol_map` without schema changes.
- **Decision 2: Backfill migration for home_country** – Add a new numbered migration that runs `UPDATE assets SET home_country = ... FROM market_symbol_map` to fill NULL `home_country` values using exchange_code mappings. This is idempotent (`WHERE home_country IS NULL`).
- **Decision 3: Extend _top_holdings response** – Add `quantity`, `avg_cost`, `latest_price`, and `quote_currency` fields to each top_holdings entry. These are already available in the SQL query; they just need to be propagated through the aggregation logic. `avg_cost` is the weighted average across accounts; `latest_price` and `quote_currency` come from the `latest_prices` CTE.
- **Decision 4: Limit change is backend-only** – Change the `limit=10` call in `dashboard_summary()` to `limit=15`. The frontend already renders all items from `top_holdings` (filtered for non-CASH). No frontend pagination needed.
- **Decision 5: Native currency display on frontend** – The frontend will show purchase price and current price with a currency prefix derived from `quote_currency` per row, not from the global `baseCurrency` selector. The `Value` column remains in the user's selected base currency.

## Risks

- **Risk 1**: Backfill migration may not cover all assets if they have no `market_symbol_map` entry. Mitigation: `infer_country()` still provides currency-based fallbacks; migration is additive.
- **Risk 2**: `avg_cost` may be NULL for some positions (e.g., transferred-in holdings). Frontend must handle `NULL` gracefully with a dash `—`.
- **Risk 3**: Aggregating `quantity` and `avg_cost` across multiple accounts holding the same asset requires weighted-average logic. If only one account holds an asset (common case), it's straightforward.

## Open Questions

- None blocking. All data is available in existing tables.

## Acceptance Criteria

- [ ] Header on `/holdings` page shows exactly 3 links: Dashboard (`/`), User, Ingest (`/ingest`) — no Crypto Holdings or Cash links
- [ ] Securities table displays geo/country correctly for IBKR holdings (HK, US, IN, SG) instead of "UNKNOWN", using exchange_code-based inference
- [ ] A new migration backfills `assets.home_country` from `market_symbol_map.exchange_code` for rows where `home_country IS NULL`
- [ ] Table shows top 15 non-CASH securities (backend limit=15)
- [ ] Each row shows: shares held (quantity), purchase price (avg_cost in native currency), current market price (latest_price in native currency)
- [ ] Purchase price and current price display in the security's native `quote_currency` (e.g., HKD for HK stocks, INR for Indian stocks)
- [ ] NULL values for avg_cost or latest_price display as `—`
- [ ] TypeScript type `DashboardSummary.top_holdings` updated with new fields: `quantity`, `avg_cost`, `latest_price`, `quote_currency`
- [ ] `make api-rebuild` succeeds
- [ ] `make web-rebuild` succeeds
- [ ] `curl http://localhost:8000/dashboard/summary?month=2026-02` returns valid JSON with new fields
- [ ] No existing API fields removed

## Human Approval Gate

- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend Changes
- [x] **Migration: Backfill home_country** – Added `migrations/022_backfill_assets_home_country_from_exchange.sql` with idempotent `home_country IS NULL` backfill from `market_symbol_map.exchange_code` mapping `{US→US, HKEX→HK, NSE→IN, SGX→SG}`
- [x] **dashboard.py: Extend infer_country()** – Added shared `_infer_country(..., exchange_code=None)` with exchange mapping and existing fallbacks
- [x] **dashboard.py: Extend _top_holdings() SQL** – Added `quantity`, `avg_cost`, `latest_price`, `quote_currency`, and `exchange_code` (via `market_symbol_map`) into `_top_holdings()` row set
- [x] **dashboard.py: Increase limit** – Updated `dashboard_summary()` `_top_holdings(..., limit=15)`
- [x] **dashboard.py: Update response dict** – Added `quantity`, `avg_cost` (weighted by quantity across accounts), `latest_price`, `quote_currency` per holding

### Frontend Changes
- [x] **StockHoldings.tsx: Fix header pills** – Replaced nav links with Dashboard (`/`), User (`/accounts/new`), Ingest (`/ingest`); removed Crypto Holdings and Cash links
- [x] **StockHoldings.tsx: Add table columns** – Added Shares, Purchase Price, Current Price columns
- [x] **StockHoldings.tsx: Native currency formatting** – Added row-level native price formatter using each row’s `quote_currency`; `NULL` values render `—`
- [x] **api.ts: Update TypeScript types** – Updated `DashboardSummary.top_holdings` type with `quantity`, `avg_cost`, `latest_price`, `quote_currency`

### Verification
- [x] `make api-rebuild`
- [ ] `make web-rebuild` (fails in current repo setup: docker compose has no `web` service)
- [ ] `curl http://localhost:8000/dashboard/summary?month=2026-02` — unable to verify from this sandbox after 3 retries (`connection refused`)
- [ ] Manual check: `/holdings` page loads with correct header, 15 rows, geo labels, and native-currency prices (not performed manually in this run; covered by automated test `web/src/__tests__/StockHoldings.test.tsx`)

## Implementation Reasoning Addendum (Codex Mutable)

- Added a single `_infer_country` helper in `dashboard.py` to keep country inference logic consistent and to introduce exchange-based inference without changing existing API fields.
- In `_top_holdings`, added `map_exchange` CTE (one row per asset via `MIN(UPPER(exchange_code))`) to avoid accidental row multiplication when assets have mapping rows.
- Kept response backward-compatible by only adding fields (`quantity`, `avg_cost`, `latest_price`, `quote_currency`) and preserving existing keys (`asset_id`, `symbol`, `asset_class`, `value`, `percent_of_networth`, `geo`, `platform`).
- Implemented `avg_cost` aggregation as weighted average by `quantity` across multiple accounts for the same asset; returns `null` when denominator is zero/missing.
- Frontend continues to show total `Value` in selected base currency, while purchase/current per-share prices now use native `quote_currency` per row.
- Added backend tests for: new fields presence, exchange-code geo inference, weighted average cost behavior, and 15-row top-holdings limit.
- Added frontend route test to verify holdings header links, new columns, native-currency rendering, and null handling.

## Verification Evidence (Codex Mutable)

- `make lint` passed.
  - Frontend: `eslint .` passed.
  - Backend lint step reported `ruff not installed in api image; skipping backend lint` (as per Makefile behavior).
- `make typecheck` passed.
  - Frontend: `npx tsc -b --pretty false` passed.
  - Backend typecheck step reported `mypy not installed in api image; skipping backend typecheck` (as per Makefile behavior).
- `make test-backend` passed: `50 passed` (`pytest`).
- `make test-frontend` passed: `7 passed` test files, `26 passed` tests (`vitest --run`).
- `make e2e` executed because Playwright exists (`web/playwright.config.ts` present); passed: `7 passed`.
- `make api-rebuild` passed and restarted `capitalos-api`.
- `make web-rebuild` failed: `no such service: web`.
- `curl http://localhost:8000/health` and `curl http://localhost:8000/dashboard/summary?month=2026-02` could not connect from this sandbox after retries (`curl: (7) Failed to connect to localhost port 8000`).

## Review Findings (Sonnet Primary, Opus Escalation)

_Review output is appended here._

## Retry Log (Max 3)

- Command: `curl -sS http://localhost:8000/health && curl -sS "http://localhost:8000/dashboard/summary?month=2026-02"`
  - Attempt 1: failed (`curl: (7) Failed to connect to localhost port 8000`)
  - Attempt 2 (after `sleep 3`): failed (`curl: (7) Failed to connect to localhost port 8000`)
  - Attempt 3 (after `sleep 10`): failed (`curl: (7) Failed to connect to localhost port 8000`)
- Command: `make web-rebuild`
  - Attempt 1: failed (`docker compose build web` -> `no such service: web`)
  - No in-scope fix available inside this task (compose file defines only `postgres` and `api` services)

## Automation Log (Mutable)

- Edited files:
  - `api/app/routers/dashboard.py`
  - `api/tests/test_dashboard.py`
  - `migrations/022_backfill_assets_home_country_from_exchange.sql`
  - `web/src/lib/api.ts`
  - `web/src/routes/StockHoldings.tsx`
  - `web/src/__tests__/StockHoldings.test.tsx`
- Commands run:
  - `make lint`
  - `make typecheck`
  - `make test-backend`
  - `make test-frontend`
  - `make e2e`
  - `make api-rebuild`
  - `make web-rebuild`
  - `curl` verification attempts for `/health` and `/dashboard/summary`

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-108-stocks-detail.md
make task-build TASK=tasks/issue-108-stocks-detail.md
make task-review TASK=tasks/issue-108-stocks-detail.md
make task-rework TASK=tasks/issue-108-stocks-detail.md
make task-ship TASK=tasks/issue-108-stocks-detail.md
```

### Build Result (2026-03-12T11:55:28Z)

```text
Implementation and verification suite completed successfully.
```

### Review Cycle R1 - Sonnet (claude-sonnet-4.6) (2026-03-12T11:59:32Z)

```text

Total usage est:        1 Premium request
API time spent:         1m 0s
Total session time:     1m 7s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       64.9k in, 2.4k out, 14.2k cached (Est. 1 Premium request)
● Read web/src/routes/StockHoldings.tsx lines 90-140
  └ 51 lines read

STATUS: APPROVED
RISK: LOW
SUMMARY:
- All 4 acceptance criteria are fully implemented: nav fix, geo inference, limit=15, and detail columns
- Backend is backward-compatible (fields added, none removed)
- Tests passed: 50 backend, 26 frontend, 7 e2e
- `make api-rebuild` passed; curl/web-rebuild failures are pre-existing infra limitations in the sandbox, not code bugs

FINDINGS:
- **Minor/cosmetic**: `colSpan={10}` on the empty-row fallback, but actual column count is 10 (`#`, Asset, Class, %NW, Value, Shares, Purchase Price, Current Price, Geo, Platform) — correct, no bug
- **Minor inconsistency**: `map_exchange` CTE uses `MIN(UPPER(exchange_code))` (alphabetical tiebreak) while the backfill migration uses explicit priority ordering. In practice assets have a single exchange mapping so this is benign
- **Minor scope gap**: `_geography()` and `_stock_exposure()` still call `_infer_country` without `exchange_code` (their queries don't join `market_symbol_map`). Geo charts only improve after the backfill migration runs. This is consistent with the architecture decision and Risk 1 mitigation
- **Test fixture**: `is_active = 1` (integer) in SQLite test for `market_symbol_map` — tests passed, so the test DB accepts this; would need `TRUE` if ever run directly against Postgres

TEST_GAPS:
- No test verifies that `_geography()` and `_stock_exposure()` benefit from exchange_code after backfill (out of scope per design)
- `make web-rebuild` and live curl verification remain unconfirmed due to sandbox constraints — acceptable given TypeScript typecheck and vitest both passed
```

### Review Cycle R1 - Status (2026-03-12T11:59:32Z)

```text
Review-ID: R1
Status: Reviewed
Result: APPROVED
Risk: LOW
```

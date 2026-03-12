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

- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Backend Changes
- [ ] **Migration: Backfill home_country** – New migration file (next sequence number) that updates `assets.home_country` from `market_symbol_map.exchange_code` using mapping `{US→US, HKEX→HK, NSE→IN, SGX→SG}` where `home_country IS NULL`
- [ ] **dashboard.py: Extend infer_country()** – Add `exchange_code` parameter with mapping to country codes; join `market_symbol_map` in `_top_holdings` query to pass exchange_code through
- [ ] **dashboard.py: Extend _top_holdings() SQL** – Add `p.quantity`, `p.avg_cost`, `lp.price AS latest_price`, and quote_currency to SELECT; propagate through aggregation (weighted avg_cost for multi-account)
- [ ] **dashboard.py: Increase limit** – Change `limit=10` to `limit=15` in `dashboard_summary()` call to `_top_holdings()`
- [ ] **dashboard.py: Update response dict** – Include `quantity`, `avg_cost`, `latest_price`, `quote_currency` in each top_holdings entry

### Frontend Changes
- [ ] **StockHoldings.tsx: Fix header pills** – Replace current pills (Dashboard, Crypto Holdings, Cash) with Dashboard (`/`), User, Ingest (`/ingest`)
- [ ] **StockHoldings.tsx: Add table columns** – Add columns: Shares, Purchase Price, Current Price (with native currency prefix per row)
- [ ] **StockHoldings.tsx: Native currency formatting** – Format purchase price and current price using `quote_currency` from each holding, not the global `baseCurrency`
- [ ] **api.ts: Update TypeScript types** – Add `quantity?: number`, `avg_cost?: number | null`, `latest_price?: number | null`, `quote_currency?: string` to `top_holdings` array type in `DashboardSummary`

### Verification
- [ ] `make api-rebuild`
- [ ] `make web-rebuild`
- [ ] `curl http://localhost:8000/dashboard/summary?month=2026-02` — verify new fields present
- [ ] Manual check: `/holdings` page loads with correct header, 15 rows, geo labels, and native-currency prices

## Implementation Reasoning Addendum (Codex Mutable)

_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)

_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)

_Review output is appended here._

## Retry Log (Max 3)

_Failed command/rework retries are appended here._

## Automation Log (Mutable)

_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-108-stocks-detail.md
make task-build TASK=tasks/issue-108-stocks-detail.md
make task-review TASK=tasks/issue-108-stocks-detail.md
make task-rework TASK=tasks/issue-108-stocks-detail.md
make task-ship TASK=tasks/issue-108-stocks-detail.md
```

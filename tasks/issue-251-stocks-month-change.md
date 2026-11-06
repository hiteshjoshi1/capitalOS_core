# Issue 251: Stocks: change per holding vs last month-end, split into price, quantity and FX (sales shown as sales)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/251

## Objective
- Stocks says how each holding changed since the month-end Overview compares with, and why: price, quantity (bought / sold) or FX (#131 review item 5, mock-up C).
- A sale is listed as a sale ("Sold"), not as a missing row or a loss, and the rows add up to Overview's bridge.

## Architecture Decisions
- D-66 (docs/decisions.md).
- One split: `app/valuation/bridge.py` gets `HoldingChange` / `holding_changes`, `AssetChange` / `asset_changes` and `stock_asset_changes`; `month_bridge` now reads its lines, movers and trades from them (no behaviour change: the bridge tests and goldens are unchanged), and `pages.stock_holdings` reads the same per-asset changes.
- Response additions only (`/dashboard/stock-holdings`): `top_holdings[].month_change`, `sold_holdings`, `month_change_total`, `compare_boundary_at`. `/summary`'s `top_holdings` is unchanged (a `StockHolding` subclass of `TopHolding` carries the new field).
- UI edits stay on the Stocks route and a new `components/StockMonthChange.tsx` (+ its own CSS file); WealthOverview untouched.

## Acceptance Criteria
- [x] Per holding, for the selected month: change vs the compare month-end (open month live vs previous month-end; past month month-end vs month-end before), split into price / quantity / FX (+ unsplit), from the bridge's split.
- [x] Holdings sold during the month listed (value 0, side "sold"); the rows add up to the bridge's stocks parts and, with `not_in_holdings`, to the Stocks headline's change.
- [x] Golden-household test of that, every instant (mid, first, first_us, SNAPSHOT_DAY=5), live and past, SGD and USD.
- [x] Table: a "Δ vs <month-end>" column, breakdown on hover (title) and tap (note), base currency, local-currency detail; P&L in the base currency with the local currency in the tooltip.
- [x] Mobile card: the change and a price / quantity / FX line, the same tap detail.
- [x] A sale reads "Sold · was S$ X", never red; a change that includes a trade isn't coloured.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_stock_month_change.py tests/test_month_bridge.py tests/test_valuation_golden.py`
- `cd web && npx vitest run src/__tests__/StockHoldings.test.tsx`
- `cd web && npx playwright test` (incl. `mobile-no-overflow.spec.ts`)
- `make verify`
- Test instance with a copy of the real data: a holding sold this month shows on Stocks as "Sold", and the rows' total matches Overview's bridge.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-opus-5.5`
- Last Updated: `2026-11-06`

### Golden files
Only additions, in the `/dashboard/stock-holdings` responses of `mid`, `first` and `first_us`; no existing figure changed:
- `compare_boundary_at`: the compare month-end's anchor (e.g. `2026-03-01T00:00:00+00:00` for March vs February).
- `top_holdings[].month_change`: each holding's split. E.g. mid, March live: AAPL +1,794.51 = price 402.30 (20 x (205 - 190) x 1.341) + quantity 1,374.54 (5 bought x 205 x 1.341) + FX 17.67 (20 x 190 x (1.341 - 1.3364)); RELIANCE +100.18 = price 7.95 + quantity 92.23 (2 bought at Sharekhan); 0700 -71.36 = price -85.89 + FX 14.53; INFY +22.26 price.
- `month_change_total`: those summed (mid March: price 346.63, quantity 1,466.77, FX 32.20) and `not_in_holdings` (0.0001, rounding), adding up to the headline's change (13,361.98 - 11,516.39 = 1,845.60).
- `sold_holdings`: `[]` (the household sells nothing; `test_a_sale_reads_as_a_sale` removes INFY from the 15 March statement to cover it).

### Demo data check (worktree stack)
- Open month and two past months, SGD and USD: per-holding price sum = the bridge's markets/stocks, FX sum = fx/stocks, rows + not_in_holdings = headline change = the bridge's stocks_funds change.
- With one demo holding deleted from the latest statement (then the stack recreated): it is listed as sold ("Sold · was S$ ..."), the rows still reconcile.
- The demo seed's statement values don't match quantity x price (#131 comment 3), so on demo data many rows show a large "Not split" part.

## Deterministic Gate Results (Codex Mutable)
- `lint`: `pass` — `make verify`
- `typecheck`: `pass` — `make verify` (tsc + mypy)
- `tests`: `pass` — `make verify`
- `e2e`: `pass` — `npx playwright test`, 36 passed; Stocks at 375px and 340px (Playwright, demo data): no horizontal overflow
- `api-smoke`: `pass` — the demo stack check above
- `policy-checks`: `pass` — no real data; demo/golden data only

## Extra Files Changed (Codex Mutable)
- `web/tests/e2e/fixtures/demo-api.json` — reason: only the `/dashboard/stock-holdings` entry re-recorded from the demo seed (new fields), so the 375px check covers the new card content; the other entries are left as they were.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR; then a test-instance batch (a sold holding reads as sold, and the Stocks rows' total matches Overview's bridge on a copy of the real data).
- Open questions:
  - Sorting the table by the change (review #131 "Sort by Δ") isn't in this issue.

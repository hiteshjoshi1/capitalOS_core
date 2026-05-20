# Issue 169: Portfolio freshness, exposure drilldowns, and snapshot comparisons

## Objective
- Replace tedious manual market refreshes with reliable automated refresh coverage across US, HK, SG, and IN holdings.
- Make stale or missing prices visible instead of silently showing partially refreshed portfolio values.
- Improve Wealth, Stock, Cash, and Crypto views with geography/currency/wallet/chain breakdowns, snapshot comparisons, and six-month mini trends.

## Problem
- Manual stock refresh can leave the portfolio half-refreshed because the current market data path refreshes a limited batch per exchange instead of guaranteeing coverage for all active mapped symbols.
- Stale quote dates are not obvious enough in the UI, so values for holdings such as Regeneron, Adobe, or Infosys can look current even when their latest stored prices are older.
- Wealth Overview still shows Upload reminders, which should be removed.
- Stock, Cash, and Crypto pages do not show enough breakdown, trend, and snapshot-comparison context to explain how current portfolio value changed.

## Architecture Decisions
- Market data refresh must have a full-coverage mode for all active mapped stock symbols, with provider-rate protections and visible per-symbol diagnostics.
- Automated refresh should be region-aware and use market timing for US, HK, SG, and IN markets. At minimum, schedule two refresh windows per 24 hours: one after Asia markets close and one after US market close.
- If provider limits require batching, the job must continue until all active mapped symbols are covered within a bounded window, and the API/UI must show which symbols remain stale or failed.
- Portfolio snapshot comparisons must use the existing `SNAPSHOT_DAY` rule. The comparison snapshot is the latest portfolio snapshot at or before the configured snapshot anchor.
- Trends should use a six-month mini trend unless the view has less history, in which case it should render the available history and indicate insufficient data through normal empty/partial states.
- Crypto movement must track both price movement and value movement, including current value, value at the last portfolio snapshot, and movement since the previous refresh where snapshot history exists.
- Exposure by chain and exposure by wallet should be rendered as pie charts.

## Scope
- Market data:
  - Add or update scheduled refresh orchestration for stocks across US, HK, SG, and IN.
  - Add a full-coverage refresh path that refreshes every active mapped stock symbol, not only the daily-limited batch.
  - Keep existing provider fallback behavior, but expose provider/source, latest trade date, age, failure reason, and skipped/deferred status per symbol.
  - Add UI diagnostics so stale, failed, or deferred symbols are obvious after refresh.
- Wealth Overview:
  - Remove Upload reminders from the Wealth Overview page.
- Stock Holdings:
  - Add geography breakdown for US, HK, SG, IN, and Other.
  - Show change from the last portfolio snapshot for each geography where data exists.
  - Surface quote freshness per holding or in a clearly visible freshness summary.
- Cash:
  - Show current cash total.
  - Show cash total at the last portfolio snapshot based on `SNAPSHOT_DAY`.
  - Show delta from the last portfolio snapshot.
  - Add six-month cash mini trend.
  - Add currency breakdown for USD, SGD, HKD, INR, and Other with snapshot deltas where data exists.
- Crypto:
  - Show current total value.
  - Show value at the last portfolio snapshot based on `SNAPSHOT_DAY`.
  - Show six-month mini trend.
  - Capture and display per-refresh up/down movement for token price and holding value.
  - Show exposure by chain as a pie chart.
  - Show exposure by wallet as a pie chart.
  - Fix or clarify month/snapshot behavior so the selected month affects displayed crypto comparisons when applicable.

## Out Of Scope
- Adding a new paid market data provider unless existing configuration already supports it.
- Broker ingestion, CSV ingestion, or parser work.
- Tax lots, realized P&L, attribution, or benchmark performance.
- Trading, rebalancing, or order execution.
- Changing the `SNAPSHOT_DAY` rule.

## Data Notes
- During planning on 2026-05-19, the stale price issue appeared to be caused by batch selection limits, not necessarily provider failure:
  - `REGN` latest stored price was 2026-05-15.
  - `ADBE` latest stored price was 2026-05-15.
  - Infosys was represented by an INR holding with latest stored price 2026-05-15.
  - Active mapped symbol counts exceeded the default per-exchange daily refresh limit for US and IN.
- Implementation should verify this against current local data rather than hardcoding any symbol-specific behavior.

## Acceptance Criteria
- [ ] Scheduled stock refresh covers all active mapped symbols across US, HK, SG, and IN within a bounded refresh window.
- [ ] Manual refresh no longer silently leaves half the portfolio stale; the result shows refreshed, failed, stale, and deferred symbols.
- [ ] Market Data UI shows per-exchange and per-symbol freshness diagnostics, including latest trade date, provider/source, and failure reason where available.
- [ ] Stock Holdings shows geography breakdown for US, HK, SG, IN, and Other.
- [ ] Stock geography breakdown shows current value and change from the last `SNAPSHOT_DAY` portfolio snapshot where data exists.
- [ ] Wealth Overview no longer renders Upload reminders.
- [ ] Cash page shows current total, last snapshot total, delta, six-month mini trend, and currency breakdown with snapshot deltas.
- [ ] Crypto page shows current value, last snapshot value, six-month mini trend, per-refresh price/value movement, and snapshot delta.
- [ ] Crypto exposure by chain and exposure by wallet render as pie charts.
- [ ] APIs remain OpenAPI-compatible, with TypeScript API types updated for all added response fields.
- [ ] Backend tests cover refresh coverage, stale diagnostics, snapshot comparison selection, stock geography deltas, cash trends, and crypto movement calculations.
- [ ] Frontend tests cover Wealth reminder removal, Stock geography breakdown, Cash totals/trend, Crypto movements, and wallet/chain pie charts.
- [ ] Verification commands are documented in the execution journal after implementation.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Inspect existing market data refresh limits, provider fallbacks, and scheduler hooks.
- [ ] Implement full-coverage region-aware stock refresh and per-symbol freshness diagnostics.
- [ ] Add backend snapshot comparison helpers for stock, cash, and crypto views.
- [ ] Update API schemas and TypeScript types.
- [ ] Update Wealth Overview, Stock Holdings, Cash, Crypto, and Market Data UI.
- [ ] Add/update backend tests.
- [ ] Add/update frontend tests.
- [ ] Run deterministic safety gates.
- [ ] Verify semantic intent is achieved with stale symbols and snapshot comparisons.

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `not_started`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-05-19`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `skip` — `not run; planning-only issue creation`
- `typecheck`: `skip` — `not run; planning-only issue creation`
- `tests`: `skip` — `not run; planning-only issue creation`
- `e2e`: `skip` — `not run; planning-only issue creation`
- `api-smoke`: `skip` — `not run; planning-only issue creation`
- `policy-checks`: `skip` — `not run; planning-only issue creation`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- None.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Run the implementation workflow for issue 169 when ready.`
- Open questions:
  - Confirm whether automatic refresh should run inside the API container, via host cron, or through the existing task runner if one is already deployed.

## Automation Log (Mutable)
_Automation appends structured logs here._

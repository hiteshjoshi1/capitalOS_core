# Issue 313: Realised P&L for any period, grouped by stock; back-fill 2025 IBKR trades

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/313

## Objective
- See which stocks made or lost money for any period (this month, YTD, last year, a year), and by how much.
- Complete 2025: the app's IBKR history starts 2025-11-03.

## Architecture Decisions (D-79)
- `realised.resolve_period` (user's calendar, end capped at today) and `realised.by_instrument`
  (per stock and account, biggest |gain or loss| first; proceeds/cost in base from each sale's own
  rate; cost-unknown and missing-FX sales named, never 0 or 1.0).
- `GET /dashboard/realised-pnl` adds `period`, `year`, `from`, `to`; the response adds `period`,
  `period_totals`, `by_instrument`, `years_with_sales`, `trades_from`, `platforms_without_trades`.
  Without `period` it is the month, exactly as #293.
- Stocks → Realised P&L: period picker (month / Year to date / Last year / Year…), a big period
  total, a per-stock table (cards at 640px and below) with gains and losses split, a drill-down to
  each stock's sales, and notes: trades before `trades_from` aren't known; Sharekhan and DBS Vickers
  give holdings only.
- `IbkrFlexClient.send_request(from_date, to_date)` sends Flex `fd`/`td`; `from_env(query_id)`.
- `make ibkr-flex-backfill FROM TO [QUERY_ID] [NO_OVERRIDE=1] [ACCOUNT] [APPLY=1]`
  (`app.portfolio.ibkr_flex_backfill`): windows of <= 365 days, paced 7s apart, each statement
  imported via `run_ibkr_flex_import_from_xml` (raw XML kept, trades replaced by execution id,
  holdings outside the authority window kept as reference). A failure prints the portal steps.

## Acceptance Criteria
- [x] Last year shows each stock's realised gain or loss and the source of each figure.
- [x] Tests: grouping, 31 Dec / 1 Jan edges, cost unknown, missing FX, bad periods, the endpoint,
      the back-fill windows, fd/td sent only when asked, the query override, dry run fetches
      nothing, apply imports once (dedup by execution id), failure + portal hint (IBKR mocked).
- [ ] After deploy: `make ibkr-flex-backfill FROM=2025-01-01 TO=2025-10-30`, then `APPLY=1`.

<!-- IMMUTABLE_PLAN_END -->

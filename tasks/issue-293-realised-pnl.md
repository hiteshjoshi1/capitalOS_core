# Issue 293: Realised P&L on sold positions

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/293

## Objective
- What selling made or lost vs what was paid, for the selected month and year to date, on Stocks.
- Overview's bridge says how much was realised, without changing its Markets total.

## Architecture Decisions (D-78)
- Flex `fifoPnlRealized` + `fxRateToBase` kept per fill in `portfolio_trades.metadata_json` (no migration);
  `make realised-pnl-backfill` (dry run; APPLY=1) fills trades stored before #293 from the kept reports.
- Per sale: IBKR's figure (source `ibkr`), else FIFO per broker account + instrument (`fifo`), else
  `cost_unknown` (left out of totals, counted). FX conversions (CASH) excluded.
- Base: the fill's IBKR rate when the requested base is the account's base; else the trade date's rate
  (D-30: none leaves it out, named).
- `GET /dashboard/realised-pnl?month=&base_currency=`: month + year-to-date totals, the month's sales.
- Bridge: Markets' total unchanged; its stocks part reads "price moves on what you hold (unrealised)" and
  a `realised` note carries the period's realised amount.

## Acceptance Criteria
- [x] Tests: FIFO partial sells across lots, unknown cost (none / too few buys), lots per instrument,
      IBKR figure wins and still closes lots, trade-date FX + missing rate left out, the fill's own rate,
      inclusive window, Flex parse keeps both values, import -> endpoint, backfill idempotent, bridge total unchanged.
- [x] Real data (read-only, rolled back): 8 sales, all with IBKR's figure, no FX gaps; FIFO alone would
      have no known cost for 7 of them (history starts after the buys).
- [ ] After deploy: `make realised-pnl-backfill`, then `APPLY=1` (71 trades).

<!-- IMMUTABLE_PLAN_END -->

# Issue 396: Stocks page UX (U4–U8 from #354)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/396

## Objective
- One baseline on the Stocks page, the full holdings list with sorting, per-platform cost and unrealised profit, and dividends per holding.

## Architecture Decisions
- D-108 (see docs/decisions.md).

## Acceptance Criteria
- [x] U4: "Change by geography" on the page's baseline (vs the compare month-end), for past months too; the "since last update" section is gone.
- [x] U5: sort by weight, change vs month-end, P&L or name, high/low; sortable column headers with aria-sort.
- [x] U6: all positions shown, sticky header in the scrolling table; Previous/Next only above 100.
- [x] U7: "Cost and unrealised profit" per platform (`platform_totals` in `/dashboard/stock-holdings`, additive).
- [x] U8: "Dividends" column (on by default, in the column picker): paid this year + trailing 12-month yield, linking to Income; mobile card line too.

## How To Test
- `cd web && npx vitest run src/__tests__/StockHoldings.test.tsx`
- `docker compose run --rm --no-deps api-dev pytest tests/test_stock_platform_totals.py tests/test_dashboard.py`
- `make e2e-smoke`

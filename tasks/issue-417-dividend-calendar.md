# Issue 417: Income: dividend calendar for the next 3 months (UX U17)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/417

## Objective
- Income shows the dividends current holdings are expected to pay over the next 3 months: when, how much (base currency), and how each is known.

## Architecture Decisions
- D-117: Yahoo (yfinance) dividend history + listed next ex-date, stored as shared market data (`market_dividend_events`, migration 087) by the market-data refresh; projected per holding at read time; the user's own payments a year back when the provider has nothing.

## Acceptance Criteria
- [x] Data-source check on the real holdings, coverage per exchange recorded (PR body, D-117).
- [x] Events stored and refreshed with the market-data refresh, capped and skipping recent fetches.
- [x] `GET /dividends/calendar` (additive) with events, per-month totals, coverage counts.
- [x] Income "Dividends, next 3 months" card, phone and desktop.
- [x] Tests with the provider mocked; cross-user isolation passes.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_dividend_calendar.py`
- `cd web && npx vitest run src/__tests__/dividendCalendar417.test.tsx`
- After deploy: a market-data refresh (Data Hub → Refresh all, as an admin) fills the events; then Income shows the card.

<!-- IMMUTABLE_PLAN_END -->

## Execution Journal
- Real data (12 Nov 2026 backup, live refresh into the worktree copy): 68 holdings got events; next 3 months S$ 1,059 gross from 11 holdings (6 listed dates, 5 projected); 39 pay at other times of year, 8 have no dividend history.

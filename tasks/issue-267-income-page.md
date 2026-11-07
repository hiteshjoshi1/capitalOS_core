# Issue 267: Income page

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/267

## Objective
- Dividends becomes Income: dividends plus interest.
- Lead with totals steady enough to compare: the last 12 months vs the 12 before, and the year to date vs the
  same dates a year earlier (month-on-month is noisy for income).

## Architecture Decisions
- `GET /income/summary?month=&base_currency=` (new; nothing removed) → `app/portfolio/income.py`.
  - Dividends: the Dividends page's rows (`_fetch_dividend_rows`: transactions + IBKR ledger, net of withholding),
    at each payment date's rate (#139).
  - Interest: the This-month bridge's rule (`valuation/bridge.py`): Cash flow income rows classified as interest
    (`income_interest` or "interest" in the category) plus the ledger's CINT/DINT. Net (broker interest charged is
    negative). Card interest charged (type INTEREST) is spending, not income.
  - Windows are app-timezone dates, half-open. The current month ends tomorrow (to date), and every comparison
    window ends on the same day of its month (like for like).
- Web: route `/income` (the same page component, `routes/Dividends.tsx`), `/dividends` redirects there; the Wealth
  tab is "Income" (matches `/dividends` too); the bridge's dividends/interest link goes to `/income`. The headline
  (last 12 months, with the split and the YTD / same-dates-last-year / year-on-year row, plus the 12 monthly bars)
  sits above the existing dividend detail ("Dividends this month", signals, history, companies).

## Acceptance Criteria
- [x] Income shows dividends + interest, last-12-months and YTD totals first, each against a year earlier.
- [x] Old `/dividends` links land on `/income`.
- [x] No comparison is shown as "no comparison", never as +100% or 0.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_income.py`
- `cd web && npx vitest run src/__tests__/Dividends.test.tsx src/__tests__/IncomeRoute.test.ts`
- Worktree stack + `make db-seed-demo`: open `/dividends` (lands on `/income`) at 1280px and 375px.

<!-- IMMUTABLE_PLAN_END -->

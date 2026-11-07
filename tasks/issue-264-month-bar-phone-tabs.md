# Issue 264: Month bar and phone tabs

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/264

## Objective
- One month + currency context per page, under the title (#131 mock-up B), instead of pills in the top bar.
- Wealth's tabs on one row that scrolls on a phone; tap targets of at least 44px on phones and touch screens.

## Architecture Decisions
- `components/MonthBar.tsx`: ◂ month picker ▸ (next stops at the current month), "Live" or the
  "Past month"/"Future month" callout plus "Back to <current>", base currency on the right.
  `PageShell` gains a `monthBar` slot rendered under the header on every width; the ten pages
  that had MonthControl + BaseCurrencyPicker in `headerActions` use it (Stocks keeps its CSV
  button in the header actions). `MonthControl` gains `hideOffMonth` (the bar shows the state).
- Section tabs: `flex-wrap: nowrap; overflow-x: auto` everywhere; the active tab is scrolled into
  view on route change and carries `aria-current="page"`.
- `@media (max-width: 980px), (pointer: coarse)`: tabs, pills, steps, theme buttons, account pill and
  bottom-nav items at least 44px tall. Phone layout of the bar: ◂ month ▸ + currency on row 1, state on row 2.

## Acceptance Criteria
- [x] Every page that follows the month shows the same bar (Overview, Stocks, Crypto, Cash, Dividends,
      Risk, History, Cash Flow, Cash Flow mapping, Liabilities).
- [x] At 375px the tabs are one scrollable row, the active one in view; no page wider than the phone.
- [x] Phone: no tab/pill/step under 44px tall (Playwright probe: 0).

## How To Test
- `cd web && npx vitest run src/__tests__/MonthBar.test.tsx src/__tests__/AppShell.test.tsx`
- Worktree stack + `make db-seed-demo` + `make web-up`; at 375px and 1280px open /wealth, /holdings,
  /wealth/history, /cash-flow, /liabilities; step back a month and use "Back to".

<!-- IMMUTABLE_PLAN_END -->

# Issue 254: One money/percent/date formatter for every page

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/254

Background: #131 review, "Numbers and formatting"; builds on #150 (D-46), which created `web/src/lib/format.ts`.

## Objective
- Every amount, percentage and date on every page comes from `web/src/lib/format.ts`, with one decimals rule.
- No raw numbers in sentences (Cash Flow's Expenses and Income headlines) and no raw ISO dates/months on screen.
- A test that fails when page-local number formatting comes back.

## Architecture Decisions
- **D-69** (refines D-46). Money decimals follow the size of the amount:
  - from 1,000 up, whole units: `S$ 53,513`;
  - below 1,000, 2 decimals: `S$ 12.40`, `-S$ 85.00`;
  - zero is `S$ 0`.

  This is `decimals: "auto"`, the new default (`moneyDecimals()`). A caller can still fix the decimals: `decimals: 2` for transaction rows and prices, `0` for chart value labels and the Cash Flow bridge.
- Compact (`S$ 35K`) is for chart labels and donut totals only. Below 1,000 it is whole units (`S$ 537`, never `S$ 537.4`). Overview's bridge part lines are text, so they now use full amounts.
- Date-times read `4 Nov, 14:05` in the current year and `4 Nov 2025, 14:05` otherwise. A bare `YYYY-MM-DD` passed to `formatDateTime` stays a date.
- New helpers: `formatDayMonth` (`4 Nov`) for due dates and freshness chips (it replaces two copies of `formatDate(...).replace(/ \d{4}$/, "")`), and `formatCsvNumber` (`1234.50`) for CSV cells.
- Currency prefixes stay as D-46: `S$` for SGD, the ISO code for the others.
- Cash Flow's Expenses and Income headlines are now written on the page, from `analytics.outflow_categories` / `inflow_source_mix` (`outflowsHeadline` / `inflowsHeadline` in `lib/cashFlowPeriod.ts`). The API's `answers` are unchanged, and no field is removed.
- `formatGuard.test.ts` gained four rules. Each fails on use outside `lib/format.ts` / `lib/chartColors.ts`:
  - `toFixed`, except CSS geometry: a `…toFixed(n)}%` on a style/width/left/gradient-stop line;
  - `Intl.NumberFormat` and `Intl.DateTimeFormat(…)` (the bare `Intl.DateTimeFormat().resolvedOptions()` timezone lookup is allowed);
  - `toLocaleTimeString`;
  - hand-built `$` prefixes.

  There is no file allowlist.
- Edits are mechanical call swaps, with no component restructuring, to keep conflicts small with #251 (Stocks), #252 (Data Hub/Overview) and #253 (Risk).

## Acceptance Criteria
- [x] One `formatMoney` / `formatPercent` / `formatDate(Time)` in `lib/format.ts` with the D-69 rules (`format.test.ts`).
- [x] Page-local copies replaced. These went: `toFixed` percentages (Risk, the hero allocation legend, AllocationCard), CSV `toFixed`, raw ISO dates (Liabilities, Market Data, Map Transactions, History drill-down, the stale-price note, the Ingest "Dated …" line), raw `YYYY-MM` months in sentences, and pure alias wrappers (CashFlowDetail `formatPercent` / `formatMonthYear`, MonthControl, Ingest `formatPreviewDate`, Market Data `formatRunStarted`).
- [x] Cash Flow Expenses and Income headlines print formatted money and percentages (`cashFlowPeriod.test.ts`, `CashFlowDetail.test.tsx`).
- [x] Guard test (`formatGuard.test.ts`, including a self-test of the CSS exemption).
- [x] Before/after screenshots of every main route at 1440 and 375 on demo data. The differences are listed below.

## How To Test
- `cd web && npx vitest run src/__tests__/format.test.ts src/__tests__/formatGuard.test.ts src/__tests__/cashFlowPeriod.test.ts`
- `cd web && npx playwright test` (the mobile overflow spec also passes at 340px)
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Visible differences (demo data, 1440 and 375, every route in `mobile-no-overflow.spec.ts`)
Taken from a text diff of each page's `#main-content` before and after, plus the screenshots. The 375 diffs match the 1440 diffs. Routes not listed are unchanged: Dividends, History, Cash, Crypto wallets, Ingest, Add account, Platforms, Alerts and Settings. Their figures are all ≥ 1,000, already 2 dp, or not money.

**Overview (`/wealth`)**
- The bridge part lines are full amounts instead of compact. Before: `stocks & funds -S$ 2.6K · crypto (usd) -S$ 1.1K · foreign-currency cash -S$ 537.4`. After: `-S$ 2,593 · -S$ 1,094 · -S$ 537.43`.
- The same applies to `income +S$ 120,000 · spending -S$ 52,313` and to the Unexplained parts (`+S$ 54,617`, `+S$ 29,742`, `+S$ 345,880`, `-S$ 38,171`).
- Top movers: `-S$ 85` becomes `-S$ 84.69`.
- Not caused by this change: net worth `S$ 16,187,699` → `S$ 16,169,699`, liabilities `S$ 5,613` → `S$ 23,613`, and the deltas and "Cards owe" line that follow from them. This is an 18,000 card charge in the demo seed whose timestamp (a time of day on today's date) passed between the two runs (22:45 and 23:05). The change is frontend formatting only and cannot move a total.

**Risk**
- Only the same net-worth clock drift (`of S$ 16,169,699 net worth`).

**Stocks (`/holdings`)**
- `Since 6 Oct 2026, 08:00` becomes `Since 6 Oct, 08:00` (current-year date-time).

**Crypto holdings**
- Per-holding deltas under 1,000 get cents: `+S$ 939 (+3.0%)` becomes `+S$ 938.99 (+3.0%)`. The same goes for 751.19, 450.72 and 300.48.

**Cash Flow (`/cash-flow`)**
- Category rows under 1,000 get cents: `S$ 196` / `+S$ 196` become `S$ 196.20` / `+S$ 196.20`.

**Cash Flow → Expenses**
- Headline before: `Most outflows went to Travel (36.9% / 30305), Household (23.7% / 19500), Shopping (11.9% / 9775).`
- Headline after: `Most outflows went to Travel S$ 30,305 (36.9%), Household S$ 19,500 (23.7%) and Shopping S$ 9,775 (11.9%).`
- Donut legend and category deltas under 1,000 get cents:
  - `S$ 800` → `S$ 800.00`
  - `S$ 660` → `S$ 660.00`
  - `S$ 403` → `S$ 402.50`
  - `S$ 196` → `S$ 196.20`
  - `S$ 115` → `S$ 114.86`
  - `S$ 10` → `S$ 10.34`
  - `+S$ 180` → `+S$ 180.00`
  - `+S$ 70` → `+S$ 70.00`

**Cash Flow → Income**
- Headline before: `Salary 95.8%, dividends 4.2%, transfers 0.0%.`
- Headline after: `Inflows came from Salary S$ 120,000 (95.8%) and Dividends S$ 5,200 (4.2%).` A source with no money is no longer listed as 0.0%.

**Map Transactions**
- `All transactions mapped for 2026-11.` becomes `All transactions mapped for November 2026.`

**Liabilities**
- Every date is `6 Nov 2026` instead of `2026-11-06`: card rows (`6 Nov 2026 · Amex Platinum Charge`), recent charges (`DBS Vantage · 3 Nov 2026`) and the transactions table's Date column.
- Card amounts under 1,000 get cents (`S$ 321` → `S$ 321.40`, `S$ 403` → `S$ 402.50`, `S$ 800` → `S$ 800.00`).
- "Single charges over S$ 50" stays whole: its threshold is fixed at 0 dp.
- The CSV download keeps ISO dates and plain numbers.

**Market Data**
- The latest trade date per symbol is `6 Nov 2026 · DUMMY` instead of `2026-11-06 · DUMMY`.

**Data Hub (`/operations`)**
- `Last import 31 Oct 2026, 22:49` becomes `Last import 31 Oct, 22:49`. The "N minutes ago" lines differ only by clock.

Not visible on demo data, but changed:
- History drill-down: "Uses data through 1 Jul 2026" instead of `2026-07-01`.
- History outlier tooltip: month name instead of `YYYY-MM`.
- Stale-price note: "statement of 30 Oct 2026".
- Ingest "Dated 1 Oct 2026 (from the file)".
- Overview mover "vs Oct 2026" when there is no %.
- Empty Cash Flow lists: "No income transactions for February 2026."
- The legacy hero/allocation cards' percentages go through `formatPercent`.

Screenshots (80 PNG plus text dumps) are kept outside the repo, in the session scratchpad (`s254/before`, `s254/after`), not committed.

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint` / `typecheck`: pass (`npx eslint .`, `npx tsc -b`; `make verify`)
- `tests`: pass (vitest 61 files / 492 tests; `make verify`)
- `e2e`: pass (`npx playwright test`: 36 passed; mobile overflow also at 340px, 22 passed)
- `api-smoke`: skip (no backend change)

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR. It touches small lines on Stocks, Risk and Overview, which #251, #252 and #253 also edit; any conflicts should be one-line call swaps.
- Open question: whether non-SGD currencies should get symbols (`US$`, `HK$`) instead of ISO codes. D-69 keeps D-46's ISO codes.

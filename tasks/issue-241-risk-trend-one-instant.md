# Issue 241: Risk page and six-month trend bars: one point in time per month

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/241

## Objective
- Every figure in one view is taken at one point in time: the open month live (as Overview since D-55), a past month at that month-end (found in #232 and #149; #131 "Risk" and the Stocks trend finding).
- The page says which point in time it shows.
- The one-number contract test (D-58) covers Risk and the trends.

## Where the "six-month trend bars" are (finding)
Three balance trends, each a six-bar chart ending at the selected month:
- **Stocks** "Six-Month Stock Trend" (`StockHoldings.tsx` → `ValueTrendChart`, data `/dashboard/stock-holdings.trend`, `valuation/holdings._stock_trend`): the open month's bar used `_completed_snapshot_anchor_ts`, so "Nov '26" repeated October's month-end under November's label (#131).
- **Cash** "Six-month cash trend" (`CashOverview.tsx` → `TrendBarChart`, `/dashboard/cash-deposits.trend`, `valuation/facts._cash_trend`): read every month at `_anchor_ts(month)`, so the open month read **its own month-end anchor, which hasn't happened yet**; so did last month before SNAPSHOT_DAY.
- **Crypto** "Six-month value trend" (`CryptoHoldings.tsx` → `TrendBarChart`, `/crypto/summary.trend`): same as Cash (`_anchor_ts`, the unpassed anchor, at the stored snapshot rows instead of the live valuation the headline uses).

Not in scope (flows, not balances; month to date by nature): Cash Flow's net cash-flow trend (`/spending/cash-flow-trend`, #243 works on Cash Flow MTD), Liabilities' card-spend trend, Dividends' 12-month income. Overview has no trend bars; History's chart already has a separate live "now" point (#138). **No Cash Flow file is touched**, so there is nothing to coordinate with #243.

## Architecture Decisions
- **D-61.** One rule for trend bars, History's (`clock._trend_point_anchor`): the open month is live "now" (month to date) and equals the page headline above the chart; a month whose month-end anchor has passed is that month-end (History's stored point); any other month (a future month; last month before SNAPSHOT_DAY) has no value. **Shown, not omitted**: the bar is labelled "MTD" and hatched, with "Nov '26 (month to date, live)" as its tooltip and screen-reader label, and the card's subtitle says "MTD: this month to date, live" when the live bar is there. Omitting it would end the chart at last month-end under a live headline.
- Trend points gain `is_live` (`MiniTrendPoint`, and crypto's dict); nothing removed.
- **Risk** (`/dashboard/risk-summary`): new `basis` ("live" / "month_end"), `view_net_worth` (live: the components `_current_networth_state` gives the Overview hero; past: the month-end `net_worth`) and `net_worth_boundary_at` (the anchor). `net_worth` keeps its meaning (/summary's month-end; the #149 twin test still pins it). The page divides cash buffer, largest position and top-N by `view_net_worth`.
- **Geography** (`/dashboard/geography-exposure`, read only by Risk) follows `_month_view_anchor` like platform allocation and stock exposure (D-55): live and quote-priced for the open month; a past month unchanged. Adds `is_live`; the card says "Live" instead of the last month-end's date.
- **Basis on the page**: subtitle "Concentration signals and geographic exposure · Live." or "… · As of 31 Oct 2026 close." (the day before the month-end anchor date, `monthEndCloseDate`); replaces "for the current snapshot". Only the subtitle string changes in the page header (#239 edits headers for mobile).

## Acceptance Criteria
- [x] Risk open month: live positions / live net worth (= Overview hero), live geography; past month: that month-end throughout.
- [x] Risk states its basis; the past-month subtitle no longer says "current snapshot".
- [x] Trend bars: open month live and labelled MTD; never an anchor that hasn't passed.
- [x] Contract test extended: Risk's net worth = Overview hero (live) / month-end (past); its stocks = the headline's stocks; geography = gross assets; each trend's open bar = the page headline, its bars for the shown and compare months = the page's figures, every other bar = History's point, and a month inside History's range with no point has no bar.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_one_number_contract.py tests/test_lean_payloads.py tests/test_valuation_clock.py tests/test_valuation_golden.py`
- `cd web && npx vitest run src/__tests__/WealthRisk.test.tsx src/__tests__/TrendLiveBar.test.tsx`
- On a stack (demo data): Risk in the current month says "Live" and its "of S$ X net worth" equals the Overview hero; a past month says "As of <last day> close" and equals that month's Overview hero. Stocks/Cash/Crypto trends end with a hatched "MTD" bar equal to the headline.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `claude-code/claude-opus-5-5`
- Last Updated: `2026-11-06`

### What changes, on the demo data (dev stack, 6 Nov 2026, SGD)
- Risk, November (live): the shares divided by October's month-end net worth (S$ 14.92M) while the positions were live; now by the live net worth (S$ 16.19M, the Overview hero). Cash buffer 12.6% → 12.0%, largest position (0700) 18.0% → 16.6%, top 5 46.5% → 42.9%. Geography was October's month-end (as of 6 Oct); now live (S$ 16.19M gross).
- Risk, October (past): unchanged (12.6%, 17.5%, 44.3%), now labelled "As of 31 Oct 2026 close".
- Stocks trend: the November bar was October's S$ 11.30M again; now S$ 12.43M = the Stocks headline, labelled MTD.
- Cash and Crypto trends: the November bar now comes from the live headline (S$ 2.44M, S$ 1.82M) instead of a read at the 1 Dec anchor; on the demo data the values happen to match.

### Golden file changes (`api/tests/golden/valuation/*.json`, `make golden-update`)
Every trend point gains `"is_live": false`, and the open month's point `"is_live": true`; `/dashboard/geography-exposure` gains `is_live`. Changed figures, all in the open month only:
- `mid` (16 Mar 2026): stocks trend 2026-03 **11516.3878 → 13361.9841** (was February's month-end repeated; now the live `stock_current_total` 13361.9841). Geography 2026-03: was February's month-end (as of 28 Feb, total 90755.0347); now live (as of 16 Mar, total **95873.7352** = live cash + stocks + crypto). Per country: SG cash 45500 → 47250; US cash 7186.57 → 4887.79, crypto 15555.76 → 19511.75, stocks 5078.18 → 6872.70; HK cash 10996.31 → 10862.21, stocks 5482.52 → 5411.16; IN stocks 955.69 → 1078.13; shares follow. Cash and crypto 2026-03 bars: values unchanged (63000.0, 21188.0184).
- `first` (1 Apr 2026, month-end just passed): stocks trend 2026-04 **13143.3186 → 13161.3742** (March's month-end at statement prices → live, quote-priced: the April headline). Geography 2026-04: total 94705.6457 → **94723.7013**, the same live total; stocks per country move from statement to quote prices (US 6839.17 → 6906.22, HK 5239.37 → 5170.66, IN 1064.77 → 1084.49); cash and crypto unchanged.
- `first_us` (31 Mar 2026 in Singapore, the 1 April anchor not yet passed): stocks trend 2026-03 **11516.3878 → 13161.3742** (February repeated → live). Geography 2026-03: February's month-end (as of 28 Feb, 90755.0347) → live (as of 31 Mar, **94723.7013**), per country as in `first` plus SG cash 45500 → 46100, US cash 7186.57 → 5255.99 and crypto 15555.76 → 19344.12.
- Every past-month figure is unchanged.

## Deterministic Gate Results (Codex Mutable)
- Backend (Docker, `pytest`): full suite passed after updating four tests for the new field and live geography (see Extra Files); contract test 9 cases, lean payloads, clock (2 new tests), goldens.
- Frontend `npx vitest run`: Risk (2 new tests), `TrendLiveBar.test.tsx` (new), Cash/Crypto/Stocks pass.
- `make verify` (2026-11-06): pass. Backend 929 passed, 25 skipped (Postgres-only); frontend 58 files / 461 tests; lint (eslint, ruff, pinned refs, migrations) and typecheck (tsc, mypy) clean.
- Browser (Playwright, demo data, 1280 px and 375 px): Risk live and past, Stocks/Cash/Crypto trend cards with the MTD bar.

## Extra Files Changed (Codex Mutable)
- `api/tests/test_crypto.py`, `api/tests/test_dashboard.py`, `api/tests/test_fx.py` — reason: exact-dict assertions on a trend point now include `is_live: False`.
- `api/tests/test_valuation_invariants.py` — reason: geography for the open month now splits the live gross assets (`current_net_worth`), not the month-end's.
- `web/src/App.css` — reason: hatched style for the live bar.
- `web/src/components/dashboard/GeographyPieCard.tsx` — reason: says "Live" for the open month.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR; test it on a test instance (Risk's net worth = Overview hero in November, = the month-end in October).
- Open questions:
  - "As of 31 Oct close" is the day before the anchor date; with SNAPSHOT_DAY > 1 it reads e.g. "As of 4 Feb close" for January's month-end, while Overview calls it "Jan 2026 month-end".
  - #131's other Risk items (largest position ignores crypto, red "below target band", currency/platform concentration) are not in this issue.

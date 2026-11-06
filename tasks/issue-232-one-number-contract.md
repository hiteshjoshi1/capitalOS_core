# Issue 232: One number everywhere: contract test that Overview, History and page headlines agree

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/232

## Objective
- The same quantity reads the same on every page: the Overview headline, the sum of its parts, History's point for the month, and the Stocks / Crypto / Cash headlines (UX review #131, top-10 item 1).
- Where two figures differ on purpose, the page says so and why.
- Every "previous" figure names its month and the date of its data.

## Architecture Decisions
- **Contract test** `api/tests/test_one_number_contract.py` over the synthetic household (`tests/valuation_household.py`) at the golden instants (`mid`, `first`, `first_us`) plus one with SNAPSHOT_DAY=5 on the 3rd, base SGD and USD, the live month and 2-3 past months. It reads the endpoints the pages read and mirrors the page's choice of figure (live: `current_net_worth`; past: `net_worth`, #223).
- **Deliberate difference, labelled:** the Cash headline includes stablecoins (D-42); `/dashboard/cash-deposits` adds `current_stablecoin_total` / `snapshot_stablecoin_total` and the page says "Includes S$ X in stablecoins, which net worth counts under Crypto".
- **Pages read a month like Overview** (D-58): Stocks, Cash and Crypto use `_month_view_anchor` and compare with `_month_view_compare_month_start` (the month-end Overview's headline compares with). Identical to before with SNAPSHOT_DAY=1; with a later SNAPSHOT_DAY, before that day, they used to read an anchor that hadn't passed.
- **Overview:** both donuts are gross assets ("GROSS ASSETS", plus "gross − liabilities = net worth"); the asset-class shares are of gross assets; the Liabilities card is the headline's liability; "vs last month/year" name their month-end, live too.
- **Dates on previous figures:** `stock-holdings.stock_snapshot_as_of` (new) on the Stocks headline; the Crypto headline adds "vs <month> (<snapshot date>)" live and past; Cash already had it.
- New response fields (additive): cash-deposits `current_stablecoin_total`, `snapshot_stablecoin_total`, `net_worth_boundary_at`; stock-holdings `stock_snapshot_as_of`. TS types mirror them.

## Acceptance Criteria
- [x] Contract test in CI (part of `make test-backend`), live and past months, SGD and USD.
- [x] No unexplained mismatch on the golden scenarios (the test passes; the mismatches it found are fixed or labelled, below).
- [x] Same comparison run read-only against the real data (GET only); result in the PR, without amounts.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_one_number_contract.py tests/test_valuation_clock.py tests/test_valuation_golden.py` (worktree: through the isolated project).
- `cd web && npx vitest run src/__tests__/WealthOverview.test.tsx src/__tests__/CashOverview.test.tsx src/__tests__/StockHoldings.test.tsx src/__tests__/CryptoHoldings.test.tsx`.
- On a stack: Overview "By asset class" and "By platform" show the same GROSS ASSETS total, with the net worth line under the legend; the Liabilities card equals the hero's liability.

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

### Mismatches found, and what was done
1. Overview Liabilities card read the last month-end's liability (`bootstrap.net_worth.liabilities`) while the live hero subtracts today's: fixed (the card shows the headline's).
2. Overview asset-class donut: TOTAL was net worth but the slices are assets (shares of net worth, adding to more than 100% with a liability); the platform donut's TOTAL was gross assets. Fixed: both are labelled gross assets, the shares are of gross assets, and a line reconciles gross − liabilities = net worth.
3. Cash headline includes stablecoins; Overview's cash doesn't (they're in Crypto): deliberate (D-42), now stated on the page with the amount, from a new response field.
4. With SNAPSHOT_DAY > 1, before that day: a past month on Stocks/Cash/Crypto read an anchor that hadn't passed (today's statements) while Overview showed the previous completed month-end, and the live pages compared with a different month than Overview's hero. Fixed (D-58). Not reachable with SNAPSHOT_DAY=1 (the real setting).
5. Previous figures without a date: Stocks headline (only the month), Crypto live headline (no compare at all), Overview live "VS LAST MONTH/YEAR" (no month). Fixed.

## Deterministic Gate Results (Codex Mutable)
- `make test-backend` (2026-11-06): 908 passed, 22 skipped (Postgres-only). The contract test: 9 cases (4 instants x SGD/USD, plus a non-zero guard).
- Frontend `npm test -- --run`: 57 files / 448 tests passed; `npx tsc -b` clean.
- `make lint` (eslint, pinned refs, migrations, ruff) and `make typecheck` (tsc, mypy): pass.
- Not checked in a browser: the Overview, Cash, Stocks and Crypto label changes are covered by component tests only.
- Real data, read-only (GET only; History's rows were current with no dirty mark, so the timeline read wrote nothing): 159 checks, live month and two past months, SGD and USD. Every Overview/History/Stocks/Crypto/Cash/allocation equality held. The page-level differences fixed here showed up: the asset-class donut total was net worth, not gross assets; the Cash headline included a stablecoin amount Overview counts under Crypto; in USD the live Liabilities card differed slightly from the hero's liability (same statement balance, converted at the month-end rate instead of today's). USD History could not be compared: no USD rows are stored, and generating them is a POST.
- Goldens regenerated (`make golden-update`): additions only (the four new fields), no figure changed.

## Extra Files Changed (Codex Mutable)
- `api/app/routers/crypto.py` — reason: the Crypto page's past-month anchor and compare month (mismatch 4).
- `api/app/valuation/clock.py` — reason: `_month_view_compare_month_start`, the one compare-month rule for month views.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR, then batch it on the test instance.
- Open questions:
  - Risk page (geography "as of" last month-end in the live month, positions live) and the six-month trend bars are outside this contract; #131 items 1 and 6 list them.
  - `openapi.json` in the repo is stale (not regenerated since the first commit); not regenerated here.

# Issue 240: Overview "This month" bridge (start, new money, markets, FX, dividends, cash kept, unexplained, end) plus top movers

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/240

## Objective
- Overview says *why* net worth changed since the last month-end close, not only by how much (#131 review item 3, mock-up A).
- The bridge always adds up: anything that can't be computed says why and sits in a shown "unexplained" residual.

## Architecture Decisions
- D-60 (docs/decisions.md): how each line is computed and what goes to "unexplained".
- A lean endpoint of its own, `GET /dashboard/month-bridge?month&base_currency[&limit]` (D-57), computed in `app/valuation/bridge.py` from the canonical readers (D-56) and the Cash flow / Dividends rows; start and end are `_networth_components`, the one-number contract figures (D-58).
- Overview edit kept self-contained: a new `components/MonthBridgeCard.tsx` (+ its own CSS file) and one insertion point below the hero, because other sprint-9 branches edit that page (#239).

## Acceptance Criteria
- [x] Endpoint returns start (previous completed month-end close = the hero's "vs last month" figure), lines (new money in; markets split stocks/crypto; FX; dividends/interest; cash kept = income - spending, month to date when live), an explicit `unexplained` residual and end (= the hero: live for the open month, month-end for a past month).
- [x] Each line has `status` / `reason` when it can't be (fully) computed; that amount is in the residual.
- [x] start + lines + unexplained = end exactly (to 1e-6), every golden instant, live and past, SGD and USD.
- [x] Top 3 movers with their dominant cause (price, quantity, FX).
- [x] Overview card below the hero, following the selected month; each line expands in place and links to its page.
- [x] D-60 decision row.
- [x] Golden files for existing endpoints unchanged.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_month_bridge.py tests/test_one_number_contract.py`
- `cd web && npx vitest run src/__tests__/MonthBridgeCard.test.tsx src/__tests__/WealthOverviewBridge.test.tsx`
- `make verify`
- Dev stack with demo data: `curl $(make api-url)/dashboard/month-bridge?month=<YYYY-MM>&base_currency=SGD` (signed in) and the card on `/wealth`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-opus-5.5`
- Last Updated: `2026-11-06`

- Test-instance follow-up (copy of the real data): a holding priced on one side only (a crypto
  token with no quote at the month-end) put its whole change in Unexplained, and dust tokens that
  lost their quote made the Markets note read "23 holdings without a price". Now the change in
  quantity is split at the priced side's price and rate, only the unpriced side's value stays
  unsplit, and the note counts holdings whose unsplit change is at least 1 in the base currency
  (`UNSPLIT_COUNT_MIN`). Sums unchanged (start + lines + unexplained = end).

## Deterministic Gate Results (Codex Mutable)
- `lint`: `pass` — `make verify`
- `typecheck`: `pass` — `make verify`
- `tests`: `pass` — `make verify` (backend in Docker, frontend vitest)
- `e2e`: `skip` — checked by hand with Playwright screenshots on the worktree stack (demo data), 1440px dark and 375px light: no horizontal overflow
- `api-smoke`: `pass` — the endpoint on the worktree stack, open and past month, SGD and USD: lines + unexplained = end - start
- `policy-checks`: `pass` — no real data; demo/golden data only

## Extra Files Changed (Codex Mutable)
- `api/tests/test_one_number_contract.py` — reason: the bridge's start/end are part of the one-number contract (asked for in the issue).
- `web/src/__tests__/api.coverage.test.ts` — reason: the new `api.monthBridge` wrapper is exercised like the others.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR; then a test-instance batch (the bridge's start and end equal the hero and the previous month-end close on a copy of the real data).
- Open questions:
  - Brokers without a cash ledger (Sharekhan, DBS Vickers, manual): their trades and deposits can't be told apart, so they show in Unexplained ("bought or sold with no cash record"). A "contribution" entry per month would make them a line.
  - The demo seed's position snapshots keep a fixed price while the value drifts, and store HKD values as if USD (#131 comment 3): on demo data the bridge shows that as a large "statement values that differ from quantity x price x rate" part.

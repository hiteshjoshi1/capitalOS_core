# Issue 223: Overview and History follow the selected month (month picker on both)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/223

## Objective
- Overview (`/wealth`) and History (`/wealth/history`) follow the same shared selected month as
  Stocks, Crypto, Cash, Cash Flow, Liabilities, Dividends and Risk (`useSelectedMonth`), with the
  `MonthControl` pill on both (UX review #131, top-10 item 4, mock-up B).
- A past month is clearly a month-end snapshot, and its comparisons are that month's (D-24).

## Current State
- `WealthOverview.tsx` pins `month` to `currentMonthYYYYMM()` ("see Wealth Timeline Phase 1 plan";
  that plan was never committed). #197 records why: its endpoints ignored `month`, so a picker did
  nothing.
- What each Overview call does with `month` today:
  - `/dashboard/bootstrap`: `net_worth` is the month's completed snapshot (honours it); the
    `current_*` fields are live (by design).
  - `/dashboard/summary`: `net_worth`, `net_worth_change`, `net_worth_component_change` and
    `top_movers` honour it; **`top_holdings`, `geography` and `cash_balances` are always live**.
  - `/dashboard/platform-allocation`: **discards `month`** (`_current_anchor_ts()`).
  - `/spending/summary`: calendar-month cash flow (honours it).
  - `/dashboard/net-worth-since-update`: live by definition (no month).
- Same latent defect: `/dashboard/stock-exposure` discards `month` (no frontend caller), and
  `/dashboard/summary?skip_networth=true` is always live.
- `WealthHistory.tsx` has its own drill-down selection; no pill; the selected month isn't marked.

## Architecture Decisions
- **One anchor rule for a month view** (`clock._month_view_anchor`): the open (or a future) month
  is live "now", exactly as today; a past month reads the same completed snapshot boundary as its
  net worth (`_completed_snapshot_anchor_ts`), at statement prices (`price_overlay=False`, as
  #144/#197 did for geography). So the hero, the donut, the positions and the movers of "Sep 2026"
  all show one month-end. The current month is unchanged on every endpoint.
- **Endpoints fixed**: `platform-allocation` (+ additive `as_of_month`, `is_live`), `summary`'s
  `top_holdings`/`geography`/`cash_balances` (+ additive `is_live`), `summary?skip_networth=true`,
  `stock-exposure` (+ additive `is_live`), `bootstrap` (+ additive `is_live`). No field removed.
- **Caching (#147)**: no response is cached; every cached helper takes the anchor (and
  `price_overlay`) as an argument, so the month is in each key. A test reads two months back to
  back with the shared cache on.
- **Overview on a past month**: the hero shows `net_worth` (the month-end snapshot), labelled
  "NET WORTH · SEP 2026 MONTH-END" and "Viewing Sep 2026 (month-end snapshot) · Back to live";
  its deltas are `net_worth_change` (that month-end vs the month-end before it and a year before,
  D-24), labelled with the baseline month ("VS AUG 2026 MONTH-END"). Live-only things are hidden:
  the freshness chips, "Since last update" and the "Today" movers tab (#131: freshness is
  meaningless for a closed month). The pill's #127 "Past month" callout is reused as is.
- **History**: the pill sets the shared month; clicking a month on the chart (or the attribution
  strip) sets it too, so there is one "selected month" in the app. The selected month is marked on
  the chart (a shaded column and a bold axis label) and its drill-down opens; the open month marks
  the "now" point (no stored row, so no drill-down). **The trend keeps the full range with the
  month marked**, rather than ending at it: at 375px the chart is already compressed, and ending
  at a past month would drop the "now" point and the months after it, so the page would stop
  answering "how did I get from there to here". The range widens to cover a selected month that
  is older than it.

## Acceptance Criteria
- [ ] Overview reads and writes the shared selected month and shows the pill; every request carries it.
- [ ] `GET /dashboard/platform-allocation?month=<past>` returns that month-end's figures; the current month is unchanged.
- [ ] Summary's positions follow a past month; the current month is unchanged.
- [ ] A past month is labelled as a month-end snapshot with a way back to live; comparisons name their baseline.
- [ ] History shows the pill, marks the selected month and opens its drill-down; chart clicks update the shared month.
- [ ] The "no month picker" test and the pinning comment are gone; tests cover the new behaviour.

## How To Test
- Backend: `docker compose run --rm --build --no-deps api-dev pytest tests/test_dashboard.py -k month`.
- Frontend: `cd web && npx vitest run src/__tests__/WealthOverview.test.tsx src/__tests__/WealthHistory.test.tsx src/__tests__/WealthHistoryChart.test.tsx`.
- Manual: pick Sep on Stocks, open Overview: it shows Sep's month-end with the callout; History marks Sep.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved (demo stack, Playwright at 1440px and 375px)

## Execution Journal (Codex Mutable)
- Current Stage: `review`
- Workflow Status: `shipped` (PR open, not merged)
- Provider/Model: `claude/claude-opus-5-5`
- Last Updated: `2026-11-06`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: pass (`make lint`: eslint, pinned refs, ruff)
- `typecheck`: pass (`npx tsc -b`, `make typecheck` mypy)
- `tests`: pass. `make test-backend`: 877 passed, 21 skipped. `npx vitest run`: 56 files, 412 passed.
- `golden`: the valuation goldens were regenerated (`UPDATE_GOLDEN=1`) for the intended change only:
  past-month `/summary` positions/geography/cash balances are now that month-end's (each past month
  used to repeat the live holdings), plus the new `is_live` / `as_of_month` fields. Current-month
  figures are unchanged.
- `e2e`: not run (mocks don't touch the changed behaviour).
- Manual: isolated stack with demo data and synthetic historical FX rates; Overview and History for
  the live month and Sep 2026 at 1440px and 375px (no page-level horizontal overflow).

## Extra Files Changed (Codex Mutable)
- `api/app/valuation/clock.py`: `_month_view_anchor`, the one anchor rule for a month view.
- `web/src/__tests__/AppShell.test.tsx`: asserted "no month picker" on Overview.
- `api/tests/test_valuation_cache.py`: past-month allocation / exposure / lean summary added to the cached-vs-uncached check.
- `docs/decisions.md`: D-54.

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR, then a test-instance batch.
- Open questions: see the PR.

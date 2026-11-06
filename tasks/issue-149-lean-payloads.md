# Issue 149: Lean page payloads: History trend, alerts count, Cash, Risk

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/149

(Not to be confused with `tasks/issue-149-alerts-realtime-subscription-migration.md`, a legacy
doc from before the board whose number collides with this issue.)

## Objective
- Pages fetch only what they show (#130 finding 5.3): History pulled the whole cash-flow detail for
  its six-month trend, Cash the whole crypto summary for the stablecoin card, Risk the whole
  `/dashboard/summary` for net worth and positions, the sidebar the whole notifications list for a
  count; `/accounts` was requested more than once per page load.
- Same numbers, same rendering: payloads and server time drop, nothing on screen changes.

## Architecture Decisions
- **Lean twin endpoints** (D-57), full endpoints unchanged (no field removed anywhere):
  - `GET /spending/cash-flow-trend?month&base_currency` → `{month, base_currency, trend, fx_*}`.
    The trend is one function, `_cash_flow_trend`, used by `/cash-flow-detail`'s `analytics.trend`
    too, so the two can't drift; the lean one skips the month's transactions, breakdowns and the
    cash reconciliation (two net-worth computations).
  - `GET /crypto/stablecoins?month&base_currency` → `{month, is_live, as_of, base_currency, symbols,
    total_base, holdings, fx_*}`: `/crypto/summary`'s USDC/USDT `top_holdings` rows (same anchor,
    same anchor-date FX rate, same order). Reads only the selected month's wallet valuation (no
    prior-month snapshot, no six-month trend). The stablecoin list moved from the Cash page to the
    server (`STABLECOIN_SYMBOLS`).
  - `GET /dashboard/risk-summary?month&base_currency` → `{as_of_month, base_currency, snapshot_day,
    is_live, net_worth, top_holdings, fx_*}`: `/summary`'s `net_worth` and `top_holdings` computed
    the way `pages.summary` computes them, each holding cut to what Risk reads (`asset_id`, `symbol`,
    `asset_class`, `value`, `percent_of_networth`). Skips geography, cash flow, cash balances,
    comparisons, movers and completeness.
  - `GET /alerts/notifications/count?month` → `{total_count}`: counts the same list
    `/alerts/notifications` returns (`_notification_items`), so badge and Alerts page agree.
- **`/accounts` once per load**: the effect-based pages (Data Hub, Import Statements, Add Accounts)
  read it through the `useApiResource` cache with a new `loadApiResource(key, fetcher, {force})`,
  which joins a request already in flight (StrictMode's double effect, or another component) and
  fills the cache for hook readers (Liabilities). Writes on Add Accounts force a fresh load.
- Each lean response's `fx_*` flags describe what that response converted; on the fixtures they
  equal the full endpoint's (tested).
- No change to `canonical_reads.py` or the valuation helpers (#231 is refactoring those); the new
  page function only calls them.

## Acceptance Criteria
- [x] Payload sizes drop (measured below, before and after, on the demo data).
- [x] Pages render the same (Playwright screenshots before/after at 1440 and 375 px, pixel-diffed).
- [x] Each lean endpoint returns exactly the full endpoint's numbers on the valuation household
      (three scenarios × open / last completed / older month × SGD and USD): `tests/test_lean_payloads.py`;
      the count: `tests/test_alerts.py::TestNotificationsCount`.
- [x] The new GET routes are in the cross-user isolation sweep, with positive controls
      (`A_SEES_OWN_DATA`).
- [x] `/accounts` is one request per page load.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_lean_payloads.py tests/test_alerts.py tests/test_cross_user_isolation.py`
- `cd web && npx vitest run`, `npx tsc -b`, `npx eslint .`; `make lint`, `make typecheck`.
- On a worktree stack with demo data: open Cash, Risk, History and the sidebar; the network tab
  shows `/crypto/stablecoins`, `/dashboard/risk-summary`, `/spending/cash-flow-trend`,
  `/alerts/notifications/count`, and one `/accounts` on Data Hub / Import Statements / Add Accounts.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Measurements (demo data, isolated worktree stack, 2026-11-06)
Server time: median of 15 interleaved calls direct to the API. "Warm" = valuation cache (#147) hot;
"uncached" = a write before every call, so the cache is invalidated (as after any import).
Timings on a shared dev machine are noisy; sizes are exact (uncompressed JSON).

| Page | Before (endpoint, size) | After (endpoint, size) | Warm ms before → after | Uncached ms before → after |
| --- | --- | --- | --- | --- |
| Risk, open month | `/dashboard/summary` 23,976 B | `/dashboard/risk-summary` 4,743 B | 31 → 17 | 144 → 62 |
| Risk, past month | `/dashboard/summary` 24,741 B | `/dashboard/risk-summary` 4,876 B | 36 → 14 | 177 → 42 |
| Cash, open month | `/crypto/summary` 16,134 B | `/crypto/stablecoins` 1,156 B | 24 → 12 | 26 → 14 |
| Cash, past month | `/crypto/summary` 16,348 B | `/crypto/stablecoins` 1,182 B | 22 → 12 | 22 → 11 |
| History | `/spending/cash-flow-detail` 21,589 B | `/spending/cash-flow-trend` 941 B | 42 → 21 | 82 → 23 |
| Sidebar (every page) | `/alerts/notifications` 39 B | `/alerts/notifications/count` 17 B | 10 → 8 | 10 → 10 |

The demo user has no upload reminders, so the notifications list is empty (39 B); each reminder
adds about 300 B to the full list and nothing to the count.

Requests per page load in the browser (dev server, StrictMode), `/api/*` only, excluding `/auth/refresh`:

| Page | Before | After |
| --- | --- | --- |
| Cash | notifications 39 B, crypto/summary 16,134 B, cash-deposits 1,630 B | notifications/count 17 B, crypto/stablecoins 1,156 B, cash-deposits 1,630 B |
| Risk | notifications 39 B, summary 23,976 B, geography 465 B | notifications/count 17 B, risk-summary 4,743 B, geography 465 B |
| History | cash-flow-detail 21,589 B ×2 (+ timeline, dividends ×2) | cash-flow-trend 941 B ×2 (+ timeline, dividends ×2) |
| Data Hub | accounts 2,500 B ×2 | accounts 2,500 B ×1 |
| Import Statements | accounts 2,500 B ×2 | accounts 2,500 B ×1 |
| Add Accounts | accounts 2,500 B ×2 | accounts 2,500 B ×1 |

The ×2 rows are React StrictMode running effect-based loads twice in development (production
builds run them once). `/accounts` now goes through the shared cache, so it is single even there.

Screenshots: `before-*.png` / `after-*.png` for 13 pages at 1440 and 375 px (kept outside the repo).
Pixel diff: identical on Cash, Risk, Stocks, Crypto, Dividends, Cash Flow, Liabilities, Import,
Add Accounts, Alerts and Overview at 1440. The only differences are live or relative-time content: the
History net-worth chart near the live "now" point (the Income vs spending card is identical), Data
Hub's "N minutes ago" activity times, and the Overview hero at 375 px.

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make lint`, `npx eslint .`
- `typecheck`: pass — `make typecheck`, `npx tsc -b`
- `tests`: pass — backend in Docker (`pytest`), `npx vitest run`
- `e2e`: pass (by hand) — Playwright before/after screenshots and request logs
- `api-smoke`: pass — curl of the four new endpoints on the worktree stack
- `policy-checks`: pass — `make lint` (pinned refs)

## Extra Files Changed (Codex Mutable)
- `web/src/lib/useApiResource.ts` — reason: `loadApiResource`, so effect-based pages share the `/accounts` cache entry.
- `web/src/lib/risk.ts` — reason: its holding type is the lean Risk row.
- `docs/decisions.md` — reason: D-57.

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR; test it on the test instance with the other batch PRs.
- Open questions:
  - Risk's cash buffer and position shares divide by `net_worth` (the month-end snapshot), while
    for the open month the positions are live; `/summary` does the same, so the lean endpoint keeps
    it. Belongs with #232 (one number everywhere).
  - History's timeline and dividends loads still run twice under StrictMode in dev (effect-based,
    not on `useApiResource`); production is unaffected.
  - At 375 px several pages are wider than the viewport (screenshots are 479–604 px wide), before
    and after this change.

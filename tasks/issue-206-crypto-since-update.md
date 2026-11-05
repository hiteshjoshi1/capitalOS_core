# Issue 206: Dashboard "since last update": crypto change is always 0

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/206

## Objective
- The dashboard's "since last update" card shows how crypto moved, like stocks and cash do.
- The total change is the sum of the component changes (cash, stocks/funds, crypto).

## Architecture Decisions
- The fix lives in `valuation/state.py` `_wallet_valuation`, the one place every reader gets
  net worth's crypto valuation from. With the price overlay, an anchor on today's date (app
  timezone) still reads the newest wallet valuation; an earlier anchor reads the valuation as
  of its date (`as_of_date=anchor_ts.date()`, the same date `_top_holdings` already uses for
  crypto, so the crypto component and the crypto movers agree).
- "Is this anchor now" compares app-local dates (`clock._local_date(anchor) >= clock._app_today()`),
  not instants: outside a request the clock isn't frozen, so two "now" anchors taken a moment
  apart would otherwise differ. No clock code changed (#202 is changing it in parallel).
- Other dateless/overlay reads checked, left as they are:
  - `valuation/facts.py` `_current_networth_state`: its anchor is always `_current_anchor_ts()`,
    and the dateless read only feeds the crypto freshness labels of "now". Correct.
  - `stock_holdings` day-compare (`_stock_exposure` at now-1d with overlay): stocks only, no wallet read.
  - `_top_holdings` (movers): crypto is already read as of the anchor date, overlay or not.
  - `summary`, `summary_without_net_worth`, `bootstrap`, `platform_allocation`, `stock_exposure`,
    `stock_holdings` when live: overlay only at the current anchor, so unchanged by this fix.
  - `routers/crypto.py`: passes `None` only when live, the anchor date otherwise. Correct.

## Acceptance Criteria
- [x] Two wallet snapshots on different days with different values: "since last update" shows
      the crypto change, and the total change equals the sum of the component changes.
- [x] Golden + invariant tests pass (no golden changed).

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_dashboard.py -q -k since_update`
  (`test_net_worth_since_update_shows_crypto_change` fails on main with crypto 0.0 vs 60.0).
- `make verify`.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass: dashboard, valuation golden/invariants/cache and crypto tests, 125 passed.
- `make verify`: pass (exit 0): backend 805 passed, 1 skipped; frontend 394 passed (55 files); 22 passed, 0 failed in the script checks.

## Extra Files Changed (Codex Mutable)
- None. `valuation/state.py` is a file shared with #202 this sprint; the change there is one function.

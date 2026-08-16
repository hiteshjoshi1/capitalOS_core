# Issue 203: Stock geography performance + daily net-worth movement

## Objective
- Show whether each geography (US/HK/SG/India) is trending up or down, separate from the existing allocation pie which only shows how much is invested where.
- Show what changed in net worth since the last price update (not just month-over-month), with a top-movers list, so daily stock/crypto price movement is visible without waiting for a monthly rollup.

## Architecture Decisions
- Decision 1: No new tables/migrations. Reuse existing anchor-parameterized aggregators
  (`_networth_components`, `_stock_exposure`, `_top_holdings`, `_top_movers_from_holdings`,
  `_stock_geography_breakdown` in `api/app/routers/dashboard.py`) called with a day-based
  compare anchor (`anchor_ts - 1 day`) instead of a month-based one. `_latest_price_map` already
  resolves "latest price ≤ anchor_date" per asset, so this yields correct as-of-last-available-price
  deltas for any anchor, including when prices are several days stale.
- Decision 2: "Since last update" is framed by the real `compare_as_of` timestamp
  (via `_effective_as_of`), never a hardcoded "1D"/"yesterday" label — if data hasn't refreshed in
  N days, the UI must say so explicitly rather than implying a fresh daily delta.
- Decision 3: `geography_performance` on `GET /dashboard/stock-holdings` is only populated when
  `is_live=True` (current/live view). For a historical month, "since yesterday" isn't meaningful
  against a fixed past boundary, so the field is null.
- Decision 4: New `GET /dashboard/net-worth-since-update` endpoint takes no `month` param — it is
  always "right now" vs. "last available prior data point," unlike the existing month-parameterized
  endpoints.
- Decision 5: Reuse existing `NetWorthChange`/`TopMover`/`TopMovers`/`StockGeographyBreakdownItem`
  Pydantic models rather than forking new ones — the `compare_month` field on `TopMover` is repurposed
  to hold the comparison timestamp label for this daily context (frontend already treats it as an
  opaque label string).
- Decision 6: Only additive changes — no existing response field is removed or renamed, per `AGENTS.md`
  API contract rules.

## Acceptance Criteria
- [ ] `GET /dashboard/stock-holdings` returns `geography_performance` (per-geography delta_abs/delta_pct
      vs. the last available prior price point) and `geography_performance_as_of`, populated only when
      `is_live=True`.
- [ ] New `GET /dashboard/net-worth-since-update?base_currency=SGD` returns total net-worth delta,
      per-component (cash/stocks_funds/crypto) delta, and top 3-5 gainers/detractors, all vs. the last
      available prior data point, with explicit `current_as_of`/`compare_as_of` timestamps.
- [ ] Stock Holdings page shows a "Geography Performance" list next to (not replacing) the existing
      allocation pie, colored by sign, with a visible "as of" caption; shows a graceful fallback copy
      for historical months where the field is null.
- [ ] Wealth Overview hero card shows a "since last update" delta strip using the new endpoint.
- [ ] Wealth Overview's existing Holdings/Movers segmented control gains a third "Today" option showing
      daily top movers via the same row UI as the existing monthly Movers tab (which remains unchanged).
- [ ] No existing API response field is removed; only additive fields/endpoints.
- [ ] Backend tests cover: correct sign/values across a synthetic two-day price change, null
      `geography_performance` for historical months, and a stale-data case (prices unchanged for
      multiple days → zero delta, not a misleading crash/omission).
- [ ] Frontend tests cover the new strip/list rendering with mocked API data in
      `StockHoldings.test.tsx` and `WealthOverview.test.tsx`.

## How To Test
- Run `make api-rebuild` then `make test-backend` (or `docker compose run --rm api pytest tests/test_dashboard.py`) and confirm the new/updated dashboard tests pass.
- Run `cd web && npx vitest run src/__tests__/StockHoldings.test.tsx src/__tests__/WealthOverview.test.tsx` and confirm they pass.
- Run `make verify` for full lint/typecheck/test coverage before considering this done.
- Manual: `make up`, log in as `demo`/`Test@1234`, open Stock Holdings and Wealth Overview, confirm the new geography performance list, since-last-update strip, and "Today" movers tab render with real seeded data.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `implementation complete`
- Workflow Status: `shipped`
- Provider/Model: `anthropic/claude-sonnet-5`
- Last Updated: `2026-08-05`

## Deterministic Gate Results (Codex Mutable)
- `backend tests`: `pass` — full `docker compose run --rm api pytest` suite green, incl. 3 new tests in `test_dashboard.py`
- `frontend tests`: `pass` — full `npx vitest run` suite green (296 tests), incl. 4 new tests
- `frontend typecheck`: `pass` — `npx tsc -b --pretty false`, exit 0

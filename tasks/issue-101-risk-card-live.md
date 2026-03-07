# Issue 101: Replace Mocked Dashboard Risk Card With Live Data

## Problem
The dashboard Risk card in `web/src/App.tsx` is hardcoded:
- Largest position is fixed (`ETH — 14.2%`)
- Top 5 concentration is fixed (`48.6%`)
- Card explicitly says `Mocked`

This is misleading because live holdings data already exists in `dashboard/summary.top_holdings`.

## Goal
Make the Risk card fully data-driven using existing API response fields.

## Scope
- Frontend only, unless absolutely necessary.
- Use `summary.top_holdings` and `summary.net_worth.total` from existing dashboard payload.
- Remove hardcoded values and mocked copy.

## Functional Requirements
1. Largest position
- Compute from `summary.top_holdings` highest `value` row.
- Show: `<SYMBOL> — <percent>%` where `percent = value / net_worth.total * 100`.
- If no holdings/net worth zero, show fallback text: `No holdings data`.

2. Top 5 concentration
- Sum top 5 holdings `value` and compute percent of net worth.
- Show computed percent with one decimal.
- If insufficient data, show `0.0%` with muted state.

3. Threshold display
- Keep threshold labels for now, but values should come from constants in code (not embedded in JSX text literals).
- Example constants:
  - `RISK_LARGEST_POSITION_WARN_PCT = 15`
  - `RISK_TOP5_TARGET_MIN_PCT = 35`
  - `RISK_TOP5_TARGET_MAX_PCT = 55`

4. Mocked text/actions
- Remove `Mocked: risk analysis...` line.
- Keep disabled buttons for now, but card must clearly show live-driven metrics.

## Non-Goals
- No backend schema changes.
- No threshold settings UI.

## Tests
1. Frontend unit test(s) for Risk card behavior:
- Case A: normal holdings -> largest and top5 values computed correctly.
- Case B: empty holdings -> graceful fallback values/text.

2. Existing test suite must pass:
- `make lint`
- `make typecheck`
- `make test-frontend`

## Manual Verification
1. Start app and API.
2. Open dashboard.
3. Confirm Risk values match arithmetic from top holdings shown elsewhere on page.
4. Confirm no mocked copy appears.

## Acceptance Criteria
- No hardcoded risk percentages remain.
- Largest position and top-5 concentration are derived from live data.
- Frontend tests added/updated and passing.

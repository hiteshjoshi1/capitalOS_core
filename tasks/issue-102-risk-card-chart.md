# Issue 102: Dashboard Risk Card Top-N Distribution (Chart)

## Summary
Enhance the existing live Dashboard Risk card to show concentration distribution for **Top 3 / Top 5 positions** with a **chart-first UI** and optional compact table.
Use existing `/dashboard/summary` data only (`top_holdings`, `net_worth.total`).

## Product Decisions
- Visualization: **Chart-first**.
- Chart library: **Recharts**.
- Top-N control: **Segmented toggle** (`Top 3`, `Top 5`), default `Top 5`.
- Data inclusion: **Include CASH** positions in concentration.
- Backend/API changes: **None**.

## Scope

### In Scope
- Add Top-3/Top-5 toggle in Risk card.
- Add Top-N concentration chart.
- Keep existing largest-position metric.
- Add/adjust frontend tests.
- Keep card live-driven (no hardcoded/mock values).

### Out of Scope
- Backend schema/API changes.
- Threshold editing/settings UX.
- User preference persistence for selected N.

## Current State
- Risk card already uses live helpers in `web/src/lib/risk.ts`.
- Risk UI is in `web/src/App.tsx`.
- Existing tests:
  - `web/src/__tests__/risk.test.ts`
  - `web/src/__tests__/App.test.tsx`

## Implementation Plan

1. Add dependency
- Add `recharts` to `web/package.json`.

2. Extend risk helpers (`web/src/lib/risk.ts`)
- Add generic Top-N helpers:
  - `computeTopNConcentration(holdings, netWorthTotal, n)`
  - `buildTopNDistribution(holdings, netWorthTotal, n)`
- Keep existing exports compatible.

3. Update Risk card UI (`web/src/App.tsx`)
- Add state: `selectedTopN: 3 | 5` (default `5`).
- Add segmented toggle.
- Render horizontal bar chart for selected N.
- Render compact table under chart:
  - Symbol, Asset Class, Value, Percent.
- Use existing formatting helpers (`formatMoney`, percent formatting).
- Keep threshold labels and existing color-state mapping.

4. Empty/partial handling
- If no holdings or `net_worth.total <= 0`: show muted no-data message.
- If holdings count < selected N:
  - show available rows only
  - show helper text: `Showing X of requested N positions`.

5. Styling
- Add minimal classes for segmented toggle and chart/table spacing.
- Keep visual consistency with dashboard card style.

## Interfaces / Types
- No backend contract changes.
- Add frontend type for chart rows (if needed), e.g.:
  - `RiskDistributionItem { symbol, assetClass, value, percent }`.

## Test Plan

### Unit Tests (`web/src/__tests__/risk.test.ts`)
- Top-3 and Top-5 percent calculations.
- Fewer-than-N holdings behavior.
- Zero net-worth guard behavior.

### UI Tests (`web/src/__tests__/App.test.tsx` or dedicated)
- Risk card renders selector.
- Default selection is Top 5.
- Toggle to Top 3 updates concentration and row count.
- Empty state rendering.

### Verification Commands
- `make lint`
- `make typecheck`
- `make test-frontend`
- If Playwright exists:
  - add minimal e2e assertion for Risk card toggle/chart presence
  - `make e2e`

## Manual Verification
1. Start API + web.
2. Open dashboard.
3. Validate largest position still correct.
4. Validate Top 5 concentration equals sum(top 5 values)/net_worth.total.
5. Toggle to Top 3 and validate recomputed concentration.
6. Confirm chart/table values align with `top_holdings`.
7. Confirm no mocked text appears.

## Acceptance Criteria
- Risk card has live Top-N chart (Top 3/Top 5).
- Toggle works and updates concentration instantly.
- CASH is included in calculations.
- No hardcoded risk percentages.
- Frontend checks pass (`lint`, `typecheck`, `test-frontend`).
- If configured, `make e2e` passes.

## Autonomous Execution Notes for Codex CLI
- Treat this as frontend-first change.
- Do not modify backend API unless blocked.
- If blocked, document blocker + exact minimal backend change proposal in `docs/plans/102.md`.
- In final plan/run report include:
  - Files changed
  - Test outputs
  - Before/after UI behavior summary
  - Any residual risks

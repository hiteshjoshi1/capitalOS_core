# Issue 197: Timeline freshness annotation + Wealth Risk geography month-picker bugfix

## Objective
- Timeline drill-down/tooltip: when a still-open month's row shows a source as stale ("OCBC as of 2026-03-06, 117d old") while an upload marker for that same source shows it "Uploaded" that same row, add an explicit note explaining the two are on different clocks — the row's freshness is anchored to its snapshot boundary, the upload marker is the real calendar date of the file landing, and the upload won't move any numbers until next month's row.
- Fix `GET /dashboard/geography-exposure`: it parses the `month` query param, discards it, and always computes from `_current_anchor_ts()` — the exact same defect class already fixed on Wealth Overview (a month picker that visibly exists but does nothing). This feeds Wealth → Risk's geography pie chart.

## Current State

**1. Timeline freshness/upload clock mismatch** — `api/app/routers/dashboard.py`:
- `_wealth_rollup_row` / `_platform_freshness_entries` compute each source's staleness relative to the row's own `anchor_date` (`_completed_snapshot_anchor_ts`, which for the still-open current month falls back to the *previous* completed boundary — e.g. a "Jul 26" row is actually anchored at 2026-07-01, not "today").
- `_timeline_upload_markers` (same file) buckets `import_jobs.created_at` by the real calendar month the file was uploaded, independent of any row's anchor.
- Result: a file uploaded July 8 shows an "Uploaded" diamond on the July row, while that same row's freshness math (anchored at July 1) still reports the source's *prior* data date as stale — both individually correct, contradictory side by side. Verified against production data: CRYPTO/OCBC/SHAREKHAN/UOB day-counts in a user-reported screenshot all check out exactly against a 2026-07-01 anchor.

**2. `/dashboard/geography-exposure` discards `month`** — `api/app/routers/dashboard.py:2396-2411`:
  ```python
  def geography_exposure(month: str = Query(...), ...):
      _parse_month(month)          # validated, then thrown away
      anchor = _current_anchor_ts()  # always "now"
      ...
  ```
  Consumed by `web/src/routes/WealthRisk.tsx` (`api.dashboardGeographyExposure(month, baseCurrency)`) — picking a different month on Wealth → Risk never changes the geography pie chart.

  The identical pattern also exists on `/dashboard/stock-exposure` (`dashboard.py:2376-2393`, no current frontend consumer — dormant) and `/dashboard/platform-allocation` (`dashboard.py:2318-2333`, consumed only by `WealthOverview.tsx`, which since the Phase 1 fix always requests the current month anyway — harmless today, but the endpoint itself still silently ignores `month` if anything else ever calls it with a historical one). Documenting both; not fixing either — no observable bug today, but same latent defect if reused.

## Architecture Decisions
- **Decision 1 (freshness annotation)**: keep upload markers on the real calendar month (immediate "yes, we saw your upload" feedback matters more than architectural purity here). Instead, when rendering a still-open month whose anchor predates one of its own upload markers, surface a caveat — e.g. in the timeline drill-down panel and the point tooltip — along the lines of "uses data through {anchor date}; recent uploads apply to next month's snapshot." Scope this to the frontend (`WealthHistoryChart.tsx` tooltip, `WealthDrilldownPanel.tsx`) using data already returned by `/dashboard/net-worth-timeline` (`anchor_date`, `uploads`, `source_freshness` per point) — no new backend field needed, this is a presentation fix.
- **Decision 2 (geography-exposure)**: wire `month` through the same way `/dashboard/stock-holdings` and `/dashboard/cash-deposits` already do — compute `month_start = _parse_month(month)`, `anchor = _completed_snapshot_anchor_ts(month_start)`, and call `_geography_exposure(db, anchor, ...)` instead of hardcoding `_current_anchor_ts()`. Leave `stock-exposure` and `platform-allocation` as documented-but-unfixed dormant instances of the same pattern (no current broken consumer to justify the change now).

## Explicitly out of scope (do not implement here)
- **Bucket B** — Stocks/Crypto/Cash pages' current-pinned hero + month picker (`StockHoldings.tsx`, `CryptoHoldings.tsx`, `CashOverview.tsx`). Deferred pending a product decision: drop the picker (same resolution as Wealth Overview) vs. make the whole page follow the selected month (matching how Dividends already works). Note for whoever picks this up: the data to support the second option already exists — `canonical_position_snapshots`, `crypto_wallet_snapshots`, and `account_balance_snapshots` are proper append-only, date-keyed tables, and `_stock_exposure`, `_top_holdings`, `_cash_deposits`, and `latest_wallet_valuation(as_of_date=...)` all already accept an arbitrary historical anchor — the current-pinned behavior is a call-site choice in each endpoint handler (hardcoding `current_anchor` instead of the requested one), not a missing-data problem.
- Credit-card analytics and removal of misleading utilization/current-balance UI are deferred to the dedicated follow-up issue and design handoff.
- Dividends, Cash Flow Detail, Cash Flow Mapping — audited, already genuinely month/transaction-scoped end to end. No changes needed.

## Acceptance Criteria
- [ ] Timeline tooltip and drill-down panel show a clear caveat on any point where a source's `as_of` predates the point's own `anchor_date` while that same source appears in `uploads` for a later month, or more simply: whenever the selected/hovered month is the current still-open month and it has any `uploads`, show "uses data through {anchor_date}; recent uploads apply next month."
- [ ] `GET /dashboard/geography-exposure?month=2025-XX` returns geography figures computed from that month's snapshot boundary, verified different from the current-month response when historical data differs.
- [ ] Wealth → Risk's geography pie chart visibly changes when a different month is selected.
- [ ] `make test-backend` and `make test-frontend` pass, including new tests for geography-exposure month-scoping and the timeline annotation.

## How To Test
- Backend: `make test-backend`, confirm new tests in `test_dashboard.py` verify geography-exposure month scoping.
- Manual: on Wealth → Risk, switch months and confirm the geography donut changes.
- Manual: open Wealth → History, hover/click the current (rightmost, still-open) month if it has an upload marker with a source older than the row's own anchor, confirm the new caveat text appears.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not started`
- Workflow Status: `blocked`
- Provider/Model: `<provider>/<model>`
- Last Updated: `2026-07-10`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Prioritize and schedule; no blocking dependency on other open issues.`
- Open questions:
  - `Bucket B (Stocks/Crypto/Cash month-picker direction) is intentionally excluded from this issue pending a separate product decision.`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-197-timeline-freshness-annotation-and-month-picker-bugfixes`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.6-sol`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Timeline tooltip and drill-down explain the different snapshot and upload clocks for a still-open month with uploads.
- Acceptance criterion: Geography exposure uses the requested month's completed snapshot boundary and differs when historical holdings differ.
- Acceptance criterion: Wealth Risk redraws geography exposure after its selected month changes.
- Acceptance criterion: Backend and frontend tests pass with new regression coverage.

## Prepare
Checked out `feature/issue-197-timeline-freshness-annotation-and-month-picker-bugfixes` from `main` and verified task file exists.

## Plan Summary
Inspected the endpoint and timeline rendering paths, implemented minimal backend and frontend changes, added regression coverage, ran all required verification gates, fixed the single test-fixture failure, and audited the final diff.

### Architecture Decisions
- Upload markers remain assigned to their real calendar upload month.
- The timeline tooltip and drill-down show the caveat for the current still-open month whenever uploads exist, using the existing anchor_date field.
- Geography exposure now resolves the requested month through _completed_snapshot_anchor_ts while leaving stock-exposure and platform-allocation unchanged as explicitly out of scope.

### Acceptance Criteria
- Timeline tooltip and drill-down explain the different snapshot and upload clocks for a still-open month with uploads.
- Geography exposure uses the requested month's completed snapshot boundary and differs when historical holdings differ.
- Wealth Risk redraws geography exposure after its selected month changes.
- Backend and frontend tests pass with new regression coverage.

### Planned Paths
- `api/app/routers/dashboard.py`
- `api/tests/test_dashboard.py`
- `web/src/components/WealthHistoryChart.tsx`
- `web/src/components/WealthDrilldownPanel.tsx`
- `web/src/__tests__/WealthHistoryChart.test.tsx`
- `web/src/__tests__/WealthDrilldownPanel.test.tsx`
- `web/src/__tests__/WealthRisk.test.tsx`

## Build Summary
Implemented timeline snapshot/upload clock caveats and fixed geography exposure month scoping.

### Changed Files
- `api/app/routers/dashboard.py`
- `api/tests/test_dashboard.py`
- `tasks/issue-197-timeline-freshness-annotation-and-month-picker-bugfixes.md`
- `web/src/__tests__/WealthDrilldownPanel.test.tsx`
- `web/src/__tests__/WealthHistoryChart.test.tsx`
- `web/src/__tests__/WealthRisk.test.tsx`
- `web/src/components/WealthDrilldownPanel.tsx`
- `web/src/components/WealthHistoryChart.tsx`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented timeline snapshot/upload clock caveats and fixed geography exposure month scoping.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.6-sol`

### Semantic Checks
- `pass` Timeline tooltip and drill-down panel show a clear caveat for the current still-open month with uploads.: Dedicated WealthHistoryChart and WealthDrilldownPanel tests verify the caveat with anchor 2026-07-01 and an OCBC upload.
- `pass` GET /dashboard/geography-exposure uses the requested historical snapshot boundary.: Backend regression verifies month 2026-05 returns SG exposure of 1000 while current month 2026-07 returns US exposure of 2000.
- `pass` Wealth Risk geography pie chart changes when a different month is selected.: WealthRisk regression changes the month to 2025-05, verifies the API call, and observes rendered stocks exposure changing from S$40,000 to S$30,000.
- `pass` Backend and frontend tests pass, including new geography month-scoping and timeline annotation tests.: Final runs passed with 1112 backend tests and 285 frontend tests, plus contract, smoke, E2E, build, lint, typecheck, and orchestration gates.

### Risk Flags
- backend_ruff_unavailable
- backend_mypy_unavailable
- pre_existing_task_journal_change_preserved

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-197-timeline-freshness-annotation-and-month-picker-bugfixes`.
<!-- MACHINE_RENDERED_END -->

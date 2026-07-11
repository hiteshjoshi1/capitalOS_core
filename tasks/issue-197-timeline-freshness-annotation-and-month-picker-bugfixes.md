# Issue 197: Timeline freshness annotation + month-picker bugfixes (Risk geography, Liabilities delta chip)

## Objective
- Timeline drill-down/tooltip: when a still-open month's row shows a source as stale ("OCBC as of 2026-03-06, 117d old") while an upload marker for that same source shows it "Uploaded" that same row, add an explicit note explaining the two are on different clocks — the row's freshness is anchored to its snapshot boundary, the upload marker is the real calendar date of the file landing, and the upload won't move any numbers until next month's row.
- Fix `GET /dashboard/geography-exposure`: it parses the `month` query param, discards it, and always computes from `_current_anchor_ts()` — the exact same defect class already fixed on Wealth Overview (a month picker that visibly exists but does nothing). This feeds Wealth → Risk's geography pie chart.
- Fix the Liabilities "vs last month" delta chip: for any credit card sourced from a synced `available_limit` (the common case), `current_due` never consults the requested month at all, so the chip shows $0 change even when the balance genuinely moved. This is worse than a no-op — it's an actively wrong signal.

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

**3. Liabilities delta chip frozen** — `api/app/routers/spending.py:798-845` (`_credit_card_items`):
  ```python
  if available_limit is not None and card["available_limit_as_of"] is not None:
      current_due = max(credit_limit - available_limit, 0.0)   # never reads `start`
      current_due_source = "available_limit"
  else:
      current_due = spend_by_account.get(int(card["account_id"]), 0.0)  # this branch IS month-scoped
      current_due_source = "transactions"
  ```
  `web/src/routes/LiabilitiesOverview.tsx:81-82` calls `creditCardTransactions(month, ...)` and `creditCardTransactions(previousMonth(month), ...)` — both hit the same `available_limit` branch, which reads a single mutable field on `credit_card_accounts` (`UNIQUE(account_id)`, no history table — see `migrations/008_credit_card_accounts.sql` + `060_credit_card_available_limit.sql`). Both calls return the identical `current_due`, so `totalCardBalance` and the delta chip are frozen for any card using this path, regardless of real movement.
  **Important constraint**: there is no historical `available_limit` to look up — this cannot be fixed by "pass month through to that branch" the way geography-exposure can. The only historically-accurate signal available without a new snapshot table is the existing transaction-sum method.

## Architecture Decisions
- **Decision 1 (freshness annotation)**: keep upload markers on the real calendar month (immediate "yes, we saw your upload" feedback matters more than architectural purity here). Instead, when rendering a still-open month whose anchor predates one of its own upload markers, surface a caveat — e.g. in the timeline drill-down panel and the point tooltip — along the lines of "uses data through {anchor date}; recent uploads apply to next month's snapshot." Scope this to the frontend (`WealthHistoryChart.tsx` tooltip, `WealthDrilldownPanel.tsx`) using data already returned by `/dashboard/net-worth-timeline` (`anchor_date`, `uploads`, `source_freshness` per point) — no new backend field needed, this is a presentation fix.
- **Decision 2 (geography-exposure)**: wire `month` through the same way `/dashboard/stock-holdings` and `/dashboard/cash-deposits` already do — compute `month_start = _parse_month(month)`, `anchor = _completed_snapshot_anchor_ts(month_start)`, and call `_geography_exposure(db, anchor, ...)` instead of hardcoding `_current_anchor_ts()`. Leave `stock-exposure` and `platform-allocation` as documented-but-unfixed dormant instances of the same pattern (no current broken consumer to justify the change now).
- **Decision 3 (Liabilities delta chip)**: change the *comparison* call only — when computing the prior month's `current_due` for the delta chip, always use the transaction-sum method (ignore `available_limit` even if present), since that's the only signal that's actually anchored to a specific historical month. The *current* month's display keeps preferring `available_limit` when available (most accurate for "now"). This likely means threading a `for_delta_only: bool` (or similar) through `_credit_card_items`, or a small sibling helper — implementer's call on the cleanest shape, but the two calls (current vs. prior) should not silently share the same frozen-value bug going forward.

## Explicitly out of scope (do not implement here)
- **Bucket B** — Stocks/Crypto/Cash pages' current-pinned hero + month picker (`StockHoldings.tsx`, `CryptoHoldings.tsx`, `CashOverview.tsx`). Deferred pending a product decision: drop the picker (same resolution as Wealth Overview) vs. make the whole page follow the selected month (matching how Dividends already works). Note for whoever picks this up: the data to support the second option already exists — `canonical_position_snapshots`, `crypto_wallet_snapshots`, and `account_balance_snapshots` are proper append-only, date-keyed tables, and `_stock_exposure`, `_top_holdings`, `_cash_deposits`, and `latest_wallet_valuation(as_of_date=...)` all already accept an arbitrary historical anchor — the current-pinned behavior is a call-site choice in each endpoint handler (hardcoding `current_anchor` instead of the requested one), not a missing-data problem. This is unlike the Liabilities case in Decision 3, where the historical data genuinely doesn't exist.
- Dividends, Cash Flow Detail, Cash Flow Mapping — audited, already genuinely month/transaction-scoped end to end. No changes needed.

## Acceptance Criteria
- [ ] Timeline tooltip and drill-down panel show a clear caveat on any point where a source's `as_of` predates the point's own `anchor_date` while that same source appears in `uploads` for a later month, or more simply: whenever the selected/hovered month is the current still-open month and it has any `uploads`, show "uses data through {anchor_date}; recent uploads apply next month."
- [ ] `GET /dashboard/geography-exposure?month=2025-XX` returns geography figures computed from that month's snapshot boundary, verified different from the current-month response when historical data differs.
- [ ] Wealth → Risk's geography pie chart visibly changes when a different month is selected.
- [ ] Liabilities "vs last month" delta chip shows a non-zero delta for an available-limit-sourced card whose balance changed between the two months (test fixture: same card, two different transaction totals in consecutive months, `available_limit` present).
- [ ] No regression to `current_due`/`totalCardBalance` for the *current* month display (still prefers `available_limit` when present).
- [ ] `make test-backend` and `make test-frontend` pass, including new tests for geography-exposure month-scoping and the credit-card delta fix.

## How To Test
- Backend: `make test-backend`, confirm new tests in `test_dashboard.py` (geography-exposure) and `test_spending.py` (credit-card delta) pass.
- Manual: on Wealth → Risk, switch months and confirm the geography donut changes. On Liabilities, seed two months of differing transaction spend for an available-limit card and confirm the delta chip moves.
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
  - `Decision 3's exact implementation shape (new param vs. sibling helper) — implementer's call.`
  - `Bucket B (Stocks/Crypto/Cash month-picker direction) is intentionally excluded from this issue pending a separate product decision.`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->

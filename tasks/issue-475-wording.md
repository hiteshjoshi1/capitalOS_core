# Issue 475: Wording & clarity (UX review #432: V1, V3, V6, V9, V11, V12, V15, V22, V24)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/475

## Objective
- Small wording and clarity fixes from the second UX review (#432), okayed for sprint S5.
- Fewer duplicate or misleading signals: one Inbox (no Alerts page), one dividends chart, one
  "needs action" count, no permanent "PARTIAL · S$ 0".

## Architecture Decisions
- V1: the Dividends page's headline and its chart say "Dividends & interest" (Cash Flow → Income is salary).
- V3: the Alerts page is removed; `/alerts` redirects to the Data Hub Inbox (`/operations`) with
  `RedirectKeepingSearch` (query string and hash kept). Smoke routes and baselines drop it.
- V6: `none_reason` (backend `NONE_REASON`, web `NO_DATA_CAUSE`) reads "Mostly market moves; no new
  statement or account explains it." Not the issue's literal "no new statement this month": a month
  usually *has* new statements, just none big enough to be a cause, so that wording would be false.
- V9: both halves, since they are one rule: the New money line is `partial` only when an estimate is
  in it (a broker with no cash record bought or sold); before, any broker with no cash record made it
  partial every month. The web hides a New money line that is zero (status ok, every part zero; its
  "transfers from your own accounts" note goes with it); the bridge still adds up. Field shapes
  unchanged. The demo fixture's month-bridge entry is edited to the new status (ok, no reason).
- V11: Realised P&L with no sales this year (month view): one line ("No sales in 2026"; for a past
  month "No sales Jan – Mar 2026", since year to date ends with the month shown). The period picker
  stays only when another year had sales.
- V12: the crypto dust rule is USD 10 converted at the page's own rate (base total / USD total),
  rounded to one significant figure (S$ 10, HKD 80, INR 800), compared with each holding's base value.
  No usable rate (no holdings, no FX): USD 10 on the USD value, as before.
- V15: the dividends-only "12-month dividend income" chart is dropped (same months as "Dividends &
  interest by month"). The calendar heading names its actual span ("Dividends expected, 24 Nov –
  23 Feb"): today + 3 months touches 4 calendar months.
- V22: the Overview strip's "N need action" uses the header bell's inbox request (shared
  `operationsInbox` cache key), so the two can't disagree; the visit reply's count is the fallback.
- V24: Home timezone: a search box narrows the list; an optgroup "Current and common" lists the
  current zone, this device's, Asia/Singapore and Asia/Kolkata first (Kolkata is offered even though
  Chrome/Node list it only as Asia/Calcutta).

## Acceptance Criteria
- [x] V1 Dividends sections say "Dividends & interest", not "Income".
- [x] V3 No Alerts page; `/alerts` opens the Inbox, query string kept; nav, tests, smoke list updated.
- [x] V6 New "why it moved" wording.
- [x] V9 No permanent "New money in · PARTIAL · S$ 0".
- [x] V11 One "No sales in <year>" line.
- [x] V12 Dust threshold in the base currency.
- [x] V15 One monthly chart; calendar label matches its tiles.
- [x] V22 One count source for the bell and the strip.
- [x] V24 Searchable timezone with current + common zones first.

## How To Test
- `cd web && npx vitest run` (InboxBell, Dividends, dividendCalendar417, MonthBridgeCard,
  RealisedPnlCard, cryptoDust475, CryptoHoldings, overviewCrypto408, UserTimezoneAndCurrency,
  MoveCauses, WealthDrilldownPanel).
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_month_bridge.py tests/test_move_causes.py`.
- `make verify`; `make e2e-smoke-update` and look at the changed PNGs.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `running`
- Provider/Model: `claude/opus`
- Last Updated: `2026-11-24`

## Deterministic Gate Results (Codex Mutable)
- See the PR's CI checks.

## Extra Files Changed (Codex Mutable)
- `web/tests/e2e/fixtures/demo-api.json` — reason: one `none_reason` string (V6), edited by hand (no re-record).

## Permanently Failed / Gave Up (Codex Mutable)
- n/a

## Human Action Summary (Codex Mutable)
- Next expected action: review on the test instance.
- Open questions:
  - V6 wording differs slightly from the issue's (see Architecture Decisions).

## Automation Log (Mutable)

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->

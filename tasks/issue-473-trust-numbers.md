# Issue 473: Numbers you can trust: stablecoins out of the Cash headline, one concentration threshold, recurring check

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/473

## Objective
- V14: the Cash page's headline no longer counts stablecoins, so Cash + Crypto + Stocks stops adding up to more than net worth.
- V16: one "concentrated" threshold: the Settings value the Risk page uses also drives the Inbox concentration alert.
- V20: "Recurring" on Cash Flow / Expenses means a regular amount at a regular interval, not "the same merchant twice".

## Architecture Decisions
- D-120 (docs/decisions.md). V14 adds `bank_broker` and `trend[].bank_broker_value` to `GET /dashboard/cash-deposits`; existing fields keep their meaning (stablecoins in). Reverses D-58's "stablecoins stay in the Cash headline".
- V16: `risk_thresholds.largest_position_warn_pct(db, user)` (Settings value, else `DEFAULT_LARGEST_POSITION_WARN_PCT` = 15, kept equal to `web/src/lib/risk.ts` by a frontend test). `INBOX_CONCENTRATION_PCT` removed. Same rule as Risk: largest by value, above (not at) the threshold.
- V20: `_is_recurring_row` uses `detect_recurring_cadence` (the Cards' rule, D-72) over the trailing 6 months per (bucket, counterparty), amounts in the row's own currency; keyword path unchanged.

## Acceptance Criteria
- [x] Cash headline reads "Bank & broker cash" and excludes stablecoins; stablecoins shown as a separate line; net worth unchanged.
- [x] Donut, currency mix, account table and trend on the Cash page match the headline (no stablecoins); the Stablecoins card stays.
- [x] Inbox concentration alert uses the Settings largest-position threshold (default 15%).
- [x] V20 verified on real data (read-only); rule tightened with tests.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_risk_concentration.py tests/test_recurring_cadence.py tests/test_one_number_contract.py tests/test_valuation_golden.py`
- `cd web && npx vitest run src/__tests__/CashOverview.test.tsx src/__tests__/risk.test.ts src/__tests__/RiskThresholdsCard.test.tsx`
- `make verify`; `make e2e-smoke-update` and look at the Cash and Cash Flow screenshots.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `shipped`
- Provider/Model: `claude/opus`
- Last Updated: `2026-11-24`

### V20 real-data check (read-only, aggregates only)
SELECT-only queries on the real stack (expense-type outflows, Jul–Nov 2026, transfers not excluded, so approximate):
- Old rule: 41–83% of outflows "recurring" per month; on cards alone 26–75%, driven by merchants seen in two
  months (supermarkets, transport, shops). Not 100% on real data, but the card side is clearly overcounted.
- New rule: 8–82% overall, almost all of it rent and salary-type payments named as such (keyword path); card
  spend 0–14% (subscriptions and a few fixed monthly charges).
- The demo's "100%" comes from its seed repeating the same merchants monthly; the new rule fixes that too.

## Deterministic Gate Results (Codex Mutable)
- `lint` / `typecheck`: pass (`make verify`)
- `tests`: pass — backend 1353 passed, 27 skipped; frontend 737 passed (`make verify`)
- `golden`: regenerated with `make golden-update`; diff = the new `bank_broker` fields, and the Cash Flow recurring split (Dining/Groceries no longer recurring, rent still is)
- `e2e`: `make e2e-smoke-update`; changed PNGs: desktop/phone cash (headline, stablecoin line, no stablecoin rows), desktop/phone cash-flow-expenses (split + rule note), phone settings/settings-admin (the threshold hint)
- `policy-checks`: pass

## Extra Files Changed (Codex Mutable)
- `api/tests/golden/valuation/*.json` — reason: cash-deposits gains `bank_broker` / `bank_broker_value`; the Cash Flow recurring split changes under the V20 rule.
- `web/tests/e2e/fixtures/demo-api.json` — reason: only the 2026-11 cash-deposits and cash-flow-detail entries, for the new fields / rule (not re-recorded). Values read from a throwaway smoke stack on the demo seed; its past-month and Cash Flow figures matched the fixture exactly; the open month's bank & broker figures are the fixture's own totals less its stablecoins.
- `api/tests/test_dashboard.py` — reason: the cash trend point gains `bank_broker_value`.

## Human Action Summary (Codex Mutable)
- Next expected action: test on the test instance (Cash page headline and stablecoin line, Inbox concentration item vs Risk, Cash Flow recurring split).

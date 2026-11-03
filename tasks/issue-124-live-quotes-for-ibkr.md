# Issue 124: Live views: price IBKR holdings with the price job's latest quote; IBKR price only as a marked fallback

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/124

## Objective
- Current-month views show the newest price for IBKR holdings, not IBKR's 1–3-day-old statement price.

## Architecture Decisions
- D-21: IBKR stays the source of truth for holdings (quantity, cost, cash, NAV). In live views a holding's price is the price job's quote when it's at least as recent as IBKR's report; the account's NAV is adjusted by (quote value - IBKR value) per holding, so the table, net worth, platform allocation and stock exposure agree.
- IBKR's price is the fallback, with a reason: `no_quote`, `quote_older`, or `quote_implausible` (quote over 2x off IBKR's value: likely a wrong symbol/currency mapping).
- Past months unchanged (snapshot values only).

## Acceptance Criteria
- [ ] Newer quote used for the holding and in all four totals.
- [ ] Fallback holdings carry a reason; the UI shows an "i" that explains it on click (desktop and phone).
- [ ] Past months unchanged.

## How To Test
- `pytest tests/test_live_quotes_ibkr.py`; `npx vitest run src/__tests__/StockHoldings.test.tsx`.
- Test instance: Stocks page, current month: REGN at the price job's 2 Nov close (961.26), not IBKR's 30 Oct 927.89.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

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
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->

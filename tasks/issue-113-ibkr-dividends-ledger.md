# Issue 113: IBKR dividends never reach the app: parse Statement of Funds into the cash ledger, Dividends page reads it

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/113

## Objective
- IBKR dividends (and their withholding tax) show on the Dividends page, from the Flex import.

## Architecture Decisions
- D-20: Statement of Funds lines are the source (`DIV`, `PIL`, `FRTAX`/`WHT`); the page reads the cash ledger alongside `transactions`, skipping an account's `transactions` dividend rows from the ledger's first date.
- No migration: each ledger line's security (conid, symbol, name) goes in `metadata_json`; the read side maps conid to `broker_instruments` for asset and country.

## Acceptance Criteria
- [ ] Real Flex XML: `StatementOfFundsLine` rows land in `portfolio_cash_ledger_entries` (was 0 rows).
- [ ] Overlapping 30-day reports store each line once; identical lines in one report don't fail the import.
- [ ] The 291 dividend of 2026-10-21 shows on the Dividends page, with US withholding when present.

## How To Test
- `docker compose run --rm --no-deps api-dev pytest tests/test_ibkr_dividends_ledger.py tests/test_ibkr_flex_phase1.py tests/test_dividends.py`
- Test instance: after one IBKR import, Dividends page for 2026-10 lists 291.

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

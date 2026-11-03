# Issue 127: Month picker: persistent past-month callout while a non-current month is selected

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/127

## Objective
- It's always obvious when a page shows a month other than the current one.

## Architecture Decisions
- In `MonthControl`, shared by every page with a month picker: a "Past month" callout (or "Future month" for one ahead) beside the pill, with an arrow pointing at it. No close control; it renders only while the month isn't the current one (`role="status"`).

## Acceptance Criteria
- [ ] Shown on every month-picker page for a non-current month, hidden for the current month, not dismissible.

## How To Test
- `npx vitest run src/__tests__/MonthControl.test.tsx`; Stocks page with September vs November at 1440px and 375px.

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

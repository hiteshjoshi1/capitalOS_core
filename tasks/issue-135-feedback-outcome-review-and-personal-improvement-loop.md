# Issue 135: Deferred Decision Records, Calibration, And Improvement

## Objective
- Hold the major later-layer work that should not block v1 value delivery.
- Defer everything that is useful only after the system already produces:
  - strong concept answers
  - strong company thesis pressure-testing
  - reusable research memory

## Program Position
- Depends on issues 131 through 134 being genuinely useful first.
- This issue exists to stop early roadmap drift into scaffolding.

## Central Product Idea
- If the system does not produce valuable outputs now, there is little point in storing, scoring, reviewing, or calibrating them.
- Therefore this issue intentionally collects the later layers:
  - explicit decision memo workflows
  - feedback capture
  - outcome review
  - calibration records
  - recurring mistake analysis
  - personal improvement analytics
  - monitoring / dashboard-style overlays

## Scope
- Explicit decision records / decision memo workflows
- Feedback capture beyond simple usefulness
- Outcome review after time passes
- Calibration and reflection records
- Pattern analysis over prior calls
- Later monitoring/reporting views that depend on stored decision history

## Out Of Scope For Earlier v1 Work
- Anything here should not be pulled into issues 131-134 unless it directly improves:
  - concept-mode answer quality now
  - company-thesis-mode answer quality now
  - research memory now

## Acceptance Criteria
- [ ] The issue documents the later-layer work that is intentionally deferred.
- [ ] No part of this issue is required before the three core user jobs are useful:
  - concept mode
  - company thesis mode
  - research memory
- [ ] When implemented later, it can cover:
  - decision memo persistence
  - memo feedback capture
  - outcome reviews
  - calibration summaries
  - recurring mistake analysis
  - personal improvement analytics

## Suggested Implementation Shape
- New persisted objects, names subject to judgment:
  - `decision_memos`
  - `decision_memo_feedback`
  - `outcome_reviews`
  - `calibration_records`
  - optional `reflection_runs`
- Later endpoints can include:
  - `POST /decision/*`
  - `GET /decision/*`
  - `GET /decision/reflection-summary`

## Verification Plan
- Not applicable for current ruthless v1 build order.
- This issue should only be implemented after issues 131-134 are already delivering user value.

## Human Notes
- Keep asking the same question:
  `Does this improve answer quality now, or is it scaffolding for later?`
- If it is scaffolding, it belongs here.

## Human Approval Gate
- [ ] Approved for implementation

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
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

# Issue 127: e2e auth fixes

## Objective
Fix Playwright E2E regressions introduced by auth (login/signup + protected routes).

Objective:
- Make all Playwright tests pass with current auth flow.
- Update tests to authenticate correctly before protected pages.
- Keep coverage of real user behavior; do not weaken assertions.

Required work:
1. Run `make e2e` and capture failing specs + root causes.
2. Patch Playwright helpers/fixtures to support authenticated sessions (login via UI or stable API/session bootstrap).
3. Update route/navigation expectations changed by auth gating.
4. Remove flaky waits; use deterministic waits tied to UI state/network.
5. Keep selectors robust (`getByRole`, stable test ids where needed).
6. Very important: Do not change product behavior only to satisfy tests unless clearly broken; if behavior is broken, fix app code and tests together. 

Verification:
- `make e2e` passes.
- `make test-frontend` passes.
- `make test-backend` passes if you change backend
- No unrelated refactors.
- Document each changed out-of-scope file in task markdown with reason (v3 policy).

Deliverables:
- Exact files changed and why.
- Short note on auth test strategy used.
- Short note on e2e coverage

## Architecture Decisions
- Decision 1:
- Decision 2:

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

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
**Current Stage**: `prepare`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: No workflow outcome recorded yet.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- retry_gate_pending: `no`

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-127-e2e-auth-fixes` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->

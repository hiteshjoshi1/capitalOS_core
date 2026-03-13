# Issue 113: Pipeline change — Remove human approval gate from `task-all`

## Objective
- Remove the human approval gate from the `task-all` orchestration flow so it runs fully automated: `plan → build → review → rework (up to MAX_RETRIES) → ship/PR`.
- Remove the `is_human_approved` check from `cmd_build()` so build can proceed without manual checkbox approval.
- Preserve all other pipeline stages (`task-plan`, `task-build`, `task-review`, `task-rework`, `task-ship`) as independently callable targets with no behavioral regressions.

## Architecture Decisions
- **AD-1: Modify only `cmd_all()` and `cmd_build()` in `scripts/task_flow.sh`.** The human gate is enforced in exactly two places: the `is_human_approved` check in `cmd_all()` (line 1364) and the `is_human_approved` guard in `cmd_build()` (line 1095). Both must be removed.
- **AD-2: Keep `is_human_approved()` function intact.** The function itself is not deleted — it remains available for any future manual-gate use or standalone `task-build` invocations. Only the calls to it are removed from `cmd_all` and `cmd_build`.
- **AD-3: Keep "Human Approval Gate" section in task file templates.** The markdown section remains in plan templates for documentation/audit trail purposes, but it is no longer enforced programmatically.
- **AD-4: Self-integrity safe.** The script uses `activate_runtime_self_integrity()` which copies the script to a temp file before running — any Codex modifications to `task_flow.sh` during a build step are validated via `bash -n` syntax check post-run. This safety net remains intact and protects against corruption.
- **AD-5: Atomic edit strategy.** Since this pipeline may be modifying itself during execution, changes must be syntactically valid at every commit. The edit involves removing/commenting out exactly 4 lines in `cmd_all()` and 1 line in `cmd_build()`. No structural changes to the script.

## Risks
- **R-1 (Medium): Self-modifying pipeline.** The `task-all` command runs `task_flow.sh`, which is the file being modified. The existing `activate_runtime_self_integrity()` mechanism mitigates this — it copies the script to `/tmp` before execution and validates syntax post-run.
- **R-2 (Low): `cmd_build` called standalone.** After removing the approval gate from `cmd_build()`, standalone `make task-build` will no longer require human approval. This is acceptable since the user explicitly requested no gate.
- **R-3 (Low): Plan output still contains "Human Approval Gate" section.** The planner prompt in `cmd_plan()` still requests this section. It becomes a no-op documentation field. No functional impact.

## Open Questions
- None. The change is well-scoped and the code paths are clear.

## Acceptance Criteria
- [ ] `cmd_all()` runs the full flow without pausing for human approval: plan → build → review → rework loop → ship
- [ ] `cmd_build()` no longer checks `is_human_approved`
- [ ] `is_human_approved()` function still exists in the script (not deleted)
- [ ] `bash -n scripts/task_flow.sh` passes (no syntax errors)
- [ ] Individual pipeline stages (`task-plan`, `task-build`, `task-review`, `task-rework`, `task-ship`) still work independently
- [ ] Self-integrity mechanism (`activate_runtime_self_integrity`) is untouched
- [ ] No other functions in the script are modified

## Human Approval Gate
- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Remove `is_human_approved` check and early-return block from `cmd_all()`
- [x] Remove `is_human_approved` guard from `cmd_build()`
- [x] Preserve `is_human_approved()` and `activate_runtime_self_integrity()` unchanged
- [x] Run `bash -n scripts/task_flow.sh` to verify syntax
- [x] Run `make lint`
- [x] Run `make typecheck`
- [x] Run `make test-backend`
- [x] Run `make test-frontend`
- [x] Run `make e2e`
- [x] Confirm no other functions in `scripts/task_flow.sh` were modified

## Implementation Reasoning Addendum (Codex Mutable)
- Updated only `scripts/task_flow.sh` and removed the two approval-gate call sites described in the immutable plan:
  - In `cmd_build()`, removed the `is_human_approved || die ...` guard so `task-build` no longer requires the checkbox gate.
  - In `cmd_all()`, removed the early-return block after `cmd_plan "$task"` so the orchestrated flow continues directly into `cmd_build "$task"`.
- Left `is_human_approved()` intact for future/manual use and left `activate_runtime_self_integrity()` untouched.
- Kept the diff atomic and scoped: no dispatch logic, retry loop logic, review/ship flow, or template text above the immutable marker was changed.
- Verified the "independently callable targets" acceptance criterion by keeping the command entry points and stage function names unchanged; only the now-obsolete gate checks were removed.

## Verification Evidence (Codex Mutable)
- `bash -n scripts/task_flow.sh`
  - Pass
- `make lint`
  - Pass on retry 1
  - First attempt failed while running in parallel with `make e2e`: ESLint hit `ENOENT` scanning `web/test-results` during Playwright artifact churn.
  - Retry completed successfully: frontend `eslint .` passed; backend lint target reported `ruff not installed in api image; skipping backend lint`.
- `make typecheck`
  - Pass
  - Frontend TypeScript build passed.
  - Backend typecheck target reported `mypy not installed in api image; skipping backend typecheck`.
- `make test-backend`
  - Pass
  - `90 passed` in Docker API test run.
- `make test-frontend`
  - Pass
  - `10` test files passed, `36` tests passed.
- `make e2e`
  - Pass
  - `7 passed` with Playwright chromium suite.
- Diff verification
  - `git diff -- scripts/task_flow.sh` shows only the removal of the `cmd_build()` approval guard and the `cmd_all()` early-return gate block.

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
- Retry 1: `make lint`
  - Initial failure: `ESLint: ENOENT: no such file or directory, scandir '/Users/hiteshjoshi/apps/capitalos/web/test-results'` while `make e2e` was running concurrently.
  - Action: reran `make lint` in isolation.
  - Result: pass.

## Automation Log (Mutable)
- Implemented approved scope in `scripts/task_flow.sh`.
- Removed approval gating from `cmd_build()` and `cmd_all()` only.
- Ran required verification commands: `bash -n scripts/task_flow.sh`, `make lint`, `make typecheck`, `make test-backend`, `make test-frontend`, `make e2e`.
- Logged one retry for `make lint`; no source changes were required beyond the approved pipeline edit.

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-113-pipline-change.md
make task-build TASK=tasks/issue-113-pipline-change.md
make task-review TASK=tasks/issue-113-pipline-change.md
make task-rework TASK=tasks/issue-113-pipline-change.md
make task-ship TASK=tasks/issue-113-pipline-change.md
```

### Build Result (2026-03-13T15:04:49Z)

```text
Implementation and verification suite completed successfully.
```

### Review Cycle R1 - Sonnet (claude-sonnet-4.6) (2026-03-13T15:09:04Z)

```text

Total usage est:        1 Premium request
API time spent:         15s
Total session time:     22s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       20.8k in, 761 out, 0 cached (Est. 1 Premium request)
STATUS: APPROVED
RISK: LOW
SUMMARY:
- Removes exactly 6 lines from `scripts/task_flow.sh`: the `is_human_approved || die` guard in `cmd_build()` and the 5-line early-return block in `cmd_all()`.
- Diff is atomic and matches the plan's AD-5 specification precisely.
- `is_human_approved()` and `activate_runtime_self_integrity()` are untouched.
- Task file updates are documentation-only.

FINDINGS:
- No logic outside the two approved call sites was modified.
- The blank line left after removing the guard in `cmd_build()` is cosmetically inert and acceptable.
- Lint retry (ENOENT on `web/test-results`) is a known race with Playwright artifact churn — not a code defect. Running in isolation passed cleanly.
- All acceptance criteria are met: 90 backend tests passed, 36 frontend tests passed, 7 e2e tests passed, `bash -n` clean.

TEST_GAPS:
- No unit test directly asserts that `cmd_all()` bypasses the gate — behavior is validated only via full integration (`make e2e`). Acceptable given the scope, but a future hardening opportunity would be a dedicated `cmd_all` smoke test that runs without a pre-approved task file.
```

### Review Cycle R1 - Status (2026-03-13T15:09:04Z)

```text
Review-ID: R1
Status: Reviewed
Result: APPROVED
Risk: LOW
```

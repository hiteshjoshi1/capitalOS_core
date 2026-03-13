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
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Remove `is_human_approved` check and early-return block from `cmd_all()` (lines 1364-1368)
- [ ] Remove `is_human_approved` guard from `cmd_build()` (line 1095)
- [ ] Run `bash -n scripts/task_flow.sh` to verify syntax
- [ ] Run `make task-all TASK=tasks/issue-113-pipline-change.md` dry-run to verify flow
- [ ] Commit with descriptive message

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

### Exact Changes Required

**File: `scripts/task_flow.sh`**

**Change 1 — `cmd_all()` (lines 1364-1368): Remove human gate block**

Remove:
```bash
  if ! is_human_approved; then
    log "Human gate pending. Review $TASK_FILE, check approval, then rerun:"
    log "scripts/task_flow.sh all $TASK_FILE"
    return 0
  fi
```

After change, `cmd_all()` becomes:
```bash
cmd_all() {
  local task="$1"
  cmd_plan "$task"
  cmd_build "$task"
  # ... review/rework loop unchanged ...
}
```

**Change 2 — `cmd_build()` (line 1095): Remove human gate check**

Remove:
```bash
  is_human_approved || die "Human gate not approved. Check '- [x] Approved for implementation' in $TASK_FILE."
```

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-113-pipline-change.md
make task-build TASK=tasks/issue-113-pipline-change.md
make task-review TASK=tasks/issue-113-pipline-change.md
make task-rework TASK=tasks/issue-113-pipline-change.md
make task-ship TASK=tasks/issue-113-pipline-change.md
```

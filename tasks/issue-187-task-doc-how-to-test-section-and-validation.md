# Issue 187: Workflow task docs - required How To Test section and validation

## Objective
- Make every implementation task file include a clear, concrete `How To Test` section before the immutable marker.
- Update orchestration templates and validation so agents do not start work from tasks that lack test instructions.
- Reduce ambiguity around "semantic intent achieved" by tying it to explicit verification commands and user-facing checks.

## Current State
- Some task files describe acceptance criteria but do not include a dedicated testing section.
- The workflow can mark semantic intent achieved based on generated evidence, but the original task may not tell the human exactly how to verify the feature.
- Missing testing instructions make handoff weaker, especially when implementation spans backend, frontend, Docker, and observability.

## Architecture Decisions
- `How To Test` belongs in the human-authored immutable region, not the mutable execution journal.
- Keep the section command-oriented and reproducible:
  - exact Makefile commands,
  - focused unit/integration commands,
  - manual curl or UI checks when relevant,
  - expected observable result.
- Add workflow validation rather than relying on convention.
- Do not require every historical task to be rewritten in one bulk migration; validate new/current task files used by the workflow.

## Implementation Plan
- Update the default task markdown template to include `## How To Test` before `<!-- IMMUTABLE_PLAN_END -->`.
- Add task markdown validation that checks for a `## How To Test` or `## Verification Plan` section before the immutable marker.
- Wire validation into `prepare` or an early orchestration stage so missing test instructions fail before agent implementation.
- Update split/planning docs or helper scripts that generate task files so new issues include the section.
- Add focused orchestration tests:
  - template includes `How To Test`,
  - a task without test instructions fails validation,
  - a task with concrete test commands passes validation,
  - missing `How To Test` failure message is actionable.
- Backfill the new section into the active observability task files if they are still unshipped when this issue is implemented.

## How To Test
- Run `make orch-test` and confirm orchestration tests pass.
- Run a focused test for task markdown validation, for example:
  - `.venv-orch/bin/python -m pytest orchestration/tests/test_task_markdown.py orchestration/tests/test_prepare.py -q`
- Create or use a temporary task file missing `How To Test` and confirm the workflow fails before agent implementation with a clear error.
- Create or use a temporary task file containing `## How To Test` before `<!-- IMMUTABLE_PLAN_END -->` and confirm validation passes.

## Acceptance Criteria
- [ ] New task template includes a `## How To Test` section before the immutable marker.
- [ ] Workflow validation rejects implementation task files that lack `How To Test` or `Verification Plan` before the immutable marker.
- [ ] Validation error tells the user exactly which section is missing and where it must appear.
- [ ] Existing current task files can be backfilled without changing their immutable intent.
- [ ] Orchestration tests cover both pass and fail cases.
- [ ] `make orch-test` passes.

## Out Of Scope
- Rewriting every historical task file.
- Changing product application behavior.
- Changing deterministic gate command definitions.
- Adding a web UI for task management.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Update task markdown template.
- [ ] Add task markdown validation.
- [ ] Wire validation into early workflow execution.
- [ ] Add focused orchestration tests.
- [ ] Backfill active task docs if needed.
- [ ] Run deterministic safety gates.
- [ ] Verify semantic intent is achieved.

## Execution Journal (Codex Mutable)
- Current Stage: `planned`
- Workflow Status: `not-started`
- Provider/Model: `manual/task-planning`
- Last Updated: `2026-07-02T00:00:00+08:00`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `orch-test`: `skip` - planning issue only
- `policy-checks`: `skip` - planning issue only

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- None.

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason:
- Attempted mitigations:
- Suggested human action:

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: run after Issue 185 is shipped or paused.
- Open questions:
  - None.

## Automation Log (Mutable)
- 2026-07-02T00:00:00+08:00 - Created workflow hardening issue for mandatory task-level testing instructions.

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `done`
**Workflow Status**: `shipped`

## Workflow Snapshot
- latest_outcome: Pushed branch `feature/issue-187-task-doc-how-to-test-section-and-validation`.
- next_action: No action required.
- pipeline_version: `v3`
- provider_model: `codex/gpt-5.5`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: New task template includes a ## How To Test section before the immutable marker.
- Acceptance criterion: Workflow validation rejects implementation task files that lack How To Test or Verification Plan before the immutable marker.
- Acceptance criterion: Validation error tells the user exactly which section is missing and where it must appear.
- Acceptance criterion: Existing current task files can be backfilled without changing their immutable intent.
- Acceptance criterion: Orchestration tests cover both pass and fail cases.
- Acceptance criterion: make orch-test passes.

## Prepare
Checked out `feature/issue-187-task-doc-how-to-test-section-and-validation` from `main` and verified task file exists.

## Plan Summary
Add validation in the task markdown service, keep template and helper generation paths aligned, add focused orchestration tests for pass/fail behavior and actionable errors, update existing mocked task fixtures, backfill current observability task files, then run the required full verification suite.

### Architecture Decisions
- Validation is centralized in TaskMarkdownService.ensure_required_markers so prepare and other early workflow consumers share the same gate.
- A valid task must contain an exact level-two section heading of either ## How To Test or ## Verification Plan before <!-- IMMUTABLE_PLAN_END -->.
- The failure message names the task file and explicitly says the required section must appear before the immutable marker.
- Legacy shell task-flow generation validation was updated to enforce the same immutable-region test section requirement.

### Acceptance Criteria
- New task template includes a ## How To Test section before the immutable marker.
- Workflow validation rejects implementation task files that lack How To Test or Verification Plan before the immutable marker.
- Validation error tells the user exactly which section is missing and where it must appear.
- Existing current task files can be backfilled without changing their immutable intent.
- Orchestration tests cover both pass and fail cases.
- make orch-test passes.

### Planned Paths
- `orchestration/services/task_markdown.py`
- `orchestration/tests/`
- `scripts/task_flow.sh`
- `tasks/_template.md`
- `tasks/issue-184-observability-logging-loki-grafana-alloy.md`
- `tasks/issue-185-api-logfmt-request-correlation-and-redaction.md`
- `tasks/issue-186-operational-logging-job-db-sampling-and-grafana-views.md`
- `tasks/issue-187-task-doc-how-to-test-section-and-validation.md`

## Build Summary
Implemented mandatory task-level testing instructions for CapitalOS orchestration: templates now include How To Test, task validation rejects missing How To Test or Verification Plan before the immutable marker, early prepare-stage validation is covered, and active observability task docs were backfilled.

### Changed Files
- `orchestration/services/task_markdown.py`
- `orchestration/tests/test_e2e_mocked.py`
- `orchestration/tests/test_escalation_rework_ship.py`
- `orchestration/tests/test_interrupt_resume.py`
- `orchestration/tests/test_prepare.py`
- `orchestration/tests/test_task_markdown.py`
- `orchestration/tests/test_v3_runtime_and_nodes.py`
- `scripts/task_flow.sh`
- `tasks/_template.md`
- `tasks/issue-184-observability-logging-loki-grafana-alloy.md`
- `tasks/issue-185-api-logfmt-request-correlation-and-redaction.md`
- `tasks/issue-186-operational-logging-job-db-sampling-and-grafana-views.md`
- `tasks/issue-187-task-doc-how-to-test-section-and-validation.md`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented mandatory task-level testing instructions for CapitalOS orchestration: templates now include How To Test, task validation rejects missing How To Test or Verification Plan before the immutable marker, early prepare-stage validation is covered, and active observability task docs were backfilled.

- semantic_intent_achieved: `True`
- provider_model: `codex/gpt-5.5`

### Semantic Checks
- `pass` New task template includes a ## How To Test section before the immutable marker.: tasks/_template.md and orchestration/services/task_markdown.py DEFAULT_TEMPLATE both include ## How To Test before <!-- IMMUTABLE_PLAN_END -->; covered by test_task_markdown.
- `pass` Workflow validation rejects implementation task files that lack How To Test or Verification Plan before the immutable marker.: TaskMarkdownService.ensure_required_markers calls ensure_test_instructions; test_task_markdown and test_prepare cover rejection.
- `pass` Validation error tells the user exactly which section is missing and where it must appear.: RuntimeError says to add ## How To Test or ## Verification Plan before <!-- IMMUTABLE_PLAN_END --> and includes the task file path.
- `pass` Existing current task files can be backfilled without changing their immutable intent.: Issues 184, 185, and 186 received command-oriented How To Test sections only; objectives, architecture decisions, scope, and acceptance criteria were not changed.
- `pass` Orchestration tests cover both pass and fail cases.: orchestration/tests/test_task_markdown.py covers missing section failure, How To Test pass, Verification Plan pass, and post-marker failure; test_prepare covers early prepare rejection.
- `pass` make orch-test passes.: make orch-test completed with 200 passed.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Ship Result
Pushed branch `feature/issue-187-task-doc-how-to-test-section-and-validation`.
<!-- MACHINE_RENDERED_END -->

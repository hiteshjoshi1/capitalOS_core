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
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->

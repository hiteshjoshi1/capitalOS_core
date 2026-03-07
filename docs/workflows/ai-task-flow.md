# CapitalOS AI Task Flow (v2.2)

This workflow is local-first and branch-safe.
All verification runs locally on your machine by default.
An optional manual GitHub Actions workflow exists and runs only when triggered explicitly.
On macOS, workflow commands automatically run under `caffeinate` to prevent laptop sleep during long runs.

Model routing:
- Planning/architecture: `claude-opus-4.6`
- Implementation/checklist updates: Codex
- Primary review/testing: `claude-sonnet-4.6`
- Escalation review only (uncertain/high-risk Sonnet review): `claude-opus-4.6`

Canonical task artifact:
- `tasks/issue-<id>-<slug>.md`

Human gate:
- Planning and implementation are separated by mandatory human approval in the task file:
  - `## Human Approval Gate`
  - `- [x] Approved for implementation`

## Lifecycle
1. `plan`
- Verifies clean worktree.
- Checks out `main`, pulls latest, and creates/switches `feature/issue-<id>-<slug>`.
- Creates task file from `tasks/_template.md` when missing.
- Runs Copilot with Opus to generate planning notes and appends output to task file.
- Commits and pushes the planning artifact.

2. Human review
- Review task file.
- Finalize architecture/acceptance criteria.
- Mark `Approved for implementation` as checked.

3. `build`
- Runs Codex implementation.
- Enforces plan integrity: immutable section (above `<!-- IMMUTABLE_PLAN_END -->`) must not change.
- Runs verification commands with max 3 retries:
  - `make lint`
  - `make typecheck`
  - `make test-backend`
  - `make test-frontend`
  - `make e2e` 

4. `review`
- Runs Sonnet review against task file + current diff.
- Escalates to Opus only when Sonnet marks uncertain/conflicting/high-risk.

5. `ship`
- Commits branch changes.
- Pushes branch.
- Creates PR to `main` if one does not already exist.

## Commands
- `scripts/task_flow.sh plan tasks/issue-123-my-task.md`
- `scripts/task_flow.sh build tasks/issue-123-my-task.md`
- `scripts/task_flow.sh review tasks/issue-123-my-task.md`
- `scripts/task_flow.sh ship tasks/issue-123-my-task.md`
- `scripts/task_flow.sh all tasks/issue-123-my-task.md`

`all` behavior:
- Runs `plan`.
- Stops if human gate is not approved.
- If approved, continues with `build -> review/rework loop -> ship`.

## Guardrails
- Never commits directly to `main`.
- Max 3 retries per failing command/rework cycle.
- All blockers are appended into task file.
- Codex must not modify immutable approved plan content.
- `caffeinate` is enabled by default (`ENABLE_CAFFEINATE=1`); set `ENABLE_CAFFEINATE=0` to disable.

## E2E Definition and Trigger
- Local E2E command is defined in `Makefile` target: `e2e`.
- `scripts/task_flow.sh build` runs `make e2e` only when Playwright config exists (`web/playwright.config.ts` or `.js`).
- If Playwright is not configured, E2E is skipped by design (not treated as failure).
- Optional manual GitHub run is defined in `.github/workflows/pr-validate.yml` with `workflow_dispatch` only.

## How to Trigger a New Feature
Input entrypoint for high-level task: task file objective section.

Git behavior for this step:
- Create the new task file first and run `make task-plan ...` without pre-committing.
- `task-plan` checks out `main`, pulls latest, creates/switches `feature/issue-<id>-<slug>`, and commits the task file on that feature branch.
- Do not commit the task file on `main` first.
- Keep tracked local changes clean before running, or branch switching can fail.

Example (UI/UX refresh):
1. Create task:
- `cp tasks/_template.md tasks/issue-103-ui-ux-refresh.md`
2. Write your high-level prompt in `## Objective`, for example:
- "Refresh dashboard UI/UX for clarity and hierarchy; improve risk card readability and mobile spacing."
3. Start workflow:
- `make task-plan TASK=tasks/issue-103-ui-ux-refresh.md`
4. Review generated plan and check:
- `- [x] Approved for implementation`
5. Continue:
- `make task-build TASK=tasks/issue-103-ui-ux-refresh.md`
- `make task-review TASK=tasks/issue-103-ui-ux-refresh.md`
- `make task-ship TASK=tasks/issue-103-ui-ux-refresh.md`

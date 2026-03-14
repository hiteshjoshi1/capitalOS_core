# CapitalOS AI Task Flow (v2.2)

This workflow is local-first and branch-safe.
All verification runs locally on your machine by default.
An optional manual GitHub Actions workflow exists and runs only when triggered explicitly.
On macOS, all main stages (`plan`, `build`, `review`, `rework`, `all`) run under `caffeinate` to prevent sleep until the stage exits.
Copilot planner/reviewer runs in `text-only` tool mode by default (no shell/write/url tools), so task files are generated from model output and not by direct Copilot file writes.

Model routing:
- Planning/architecture: `claude-opus-4.6`
- Implementation/checklist updates: Codex
- Primary review/testing: `claude-sonnet-4.6`
- Escalation review only (uncertain/high-risk Sonnet review): `claude-opus-4.6`

## Configuration
- Workflow runtime config is loaded from repo-root `.ai-models.env`.
- Keys: `PLAN_MODEL`, `REVIEW_MODEL`, `REVIEW_ESCALATION_MODEL`, `CODEX_TIMEOUT_MINUTES`, `ENABLE_CAFFEINATE`, `COPILOT_TOOL_MODE`, `CONTEXT7_ENABLED`, `COPILOT_MCP_CONFIG`, `MAX_RETRIES`, `NO_CACHE`.
- Existing shell env overrides remain supported and take precedence over `.ai-models.env`.
- `./scripts/task_flow.sh --verbose ...` prints the active routing table.

## Task Context
- `plan` and `review` send the full task file content to the model (no compaction).
- Task file on disk is used as-is for prompt context.

## Caching
- Cache directory: `.task-cache/` (gitignored).
- Applies only to `plan` and `review` model calls.
- Cache key: `sha256(phase + model + full_task_content + git_tree_hash)`.
- Cache stores response text (`.txt`) and metadata (`.meta`).
- Set `NO_CACHE=1` to bypass cache.
- Clear cache with `make task-cache-clean`.

## Context7 Integration
- Optional and off by default: `CONTEXT7_ENABLED=0`.
- When enabled and configured, `plan`/`review` Copilot calls include `--allow-tool context7`.
- Config file path: `COPILOT_MCP_CONFIG` (defaults to `~/.copilot/mcp-config.json`).
- If Context7 invocation fails, workflow logs a warning and retries the same call without Context7.
- Expected config shape includes `mcpServers.context7` (HTTP MCP endpoint).

Canonical task artifact:
- `tasks/issue-<id>-<slug>.md`

Human gate:
- Planning and implementation are separated by mandatory human approval in the task file:
  - `## Human Approval Gate`
  - `- [x] Approved for implementation`

## Lifecycle
0. `prepare`
- Uses your local task file as input.
- Verifies no other working-tree changes are present.
- Checks out `main`, pulls latest, creates/switches `feature/issue-<id>-<slug>`, restores the task file there, commits, and pushes.
- Leaves branch clean and ready for `plan`.

1. `plan`
- Verifies clean worktree.
- Checks out `main`, pulls latest, and creates/switches `feature/issue-<id>-<slug>` (reuses existing branch; does not recreate).
- If already on the target issue branch, allows local changes only in that task file and plans in place.
- Creates task file from `tasks/_template.md` when missing.
- Runs Copilot with Opus and writes a clean structured plan into the task file (CLI transcript stays in terminal output, not in the file).
- Planning output includes copy/paste `make` commands with the exact task filename.
- Workflow command section is normalized by script to canonical `make task-* TASK=<file>` commands.
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
- Auto-stages changes (`git add -A`) at the end for review handoff.

4. `review`
- Independently reruns deterministic verification in bash (no model tool execution):
  - `make lint`
  - `make typecheck`
  - `make test-backend`
  - `make test-frontend`
  - `make api-smoke`
  - `make e2e` when Playwright is configured (used as UI smoke)
- Captures verification output and UI artifact index (`web/playwright-report`, `web/test-results`) as review evidence.
- Runs Sonnet review against task file + current diff + captured verification/UI evidence.
- Escalates to Opus only when Sonnet marks uncertain/conflicting/high-risk.
- Logs a new review cycle section each run (for example `Review Cycle R1`) and marks status `Reviewed`.
- Requires all review inputs to be staged (manual `task-review`); otherwise exits with instruction.

5. `rework`
- Requires structured human input for latest cycle under:
  - `### Review Cycle R<n> - Human Input`
  - `HUMAN_QUESTIONS: ...`
  - `UNRESOLVED_COMMENTS: ...`
  - `RESPONSE_REQUIREMENTS: ...`
- Runs two-pass Codex rework:
  - Analysis pass first (diagnose/justify only), writing:
    - `Review Cycle R<n> - Rework Analysis`
    - `Review Cycle R<n> - Rework Answer Matrix`
  - Implementation pass second (patch/verify), updating same answer matrix with actual changes and verification.
- Required answer-matrix fields per entry:
  - `REVIEWER_FINDING`
  - `HUMAN_COMMENT`
  - `ROOT_CAUSE`
  - `CHANGE_MADE`
  - `VERIFICATION_PERFORMED`
  - `STATUS`
- Marks latest review cycle status as `Implemented`.
- Prevents duplicate rework for the same review cycle.
- Auto-stages changes (`git add -A`) at the end for next review pass.

Review gate enforcement:
- `task-review` fails fast if latest implemented cycle is missing either:
  - `Rework Analysis`, or
  - `Rework Answer Matrix`.

6. `ship`
- Commits branch changes.
- Pushes branch.
- Creates PR to `main` if one does not already exist.

## Commands
- `scripts/task_flow.sh prepare tasks/issue-123-my-task.md`
- `scripts/task_flow.sh plan tasks/issue-123-my-task.md`
- `scripts/task_flow.sh build tasks/issue-123-my-task.md`
- `scripts/task_flow.sh review tasks/issue-123-my-task.md`
- `scripts/task_flow.sh rework tasks/issue-123-my-task.md`
- `scripts/task_flow.sh ship tasks/issue-123-my-task.md`
- `scripts/task_flow.sh all tasks/issue-123-my-task.md`

`all` behavior:
- Runs `plan`.
- Stops if human gate is not approved.
- If approved, continues with `build -> review/rework loop -> ship`.
- Auto-stages (`git add -A`) before each review cycle so reviewer sees complete snapshot.

## Guardrails
- Never commits directly to `main`.
- Max 3 retries per failing command/rework cycle.
- All blockers are appended into task file.
- Codex must not modify immutable approved plan content.
- `caffeinate` is enabled by default (`ENABLE_CAFFEINATE=1`); set `ENABLE_CAFFEINATE=0` to disable.
- `caffeinate` scope covers `plan`, `build`, `review`, `rework`, and `all`.
- Copilot tool mode defaults to `COPILOT_TOOL_MODE=text-only`; set `COPILOT_TOOL_MODE=tools-enabled` only if you explicitly want Copilot tool calls.

## E2E Definition and Trigger
- Local E2E command is defined in `Makefile` target: `e2e`.
- `scripts/task_flow.sh build` runs `make e2e` only when Playwright config exists (`web/playwright.config.ts` or `.js`).
- If Playwright is not configured, E2E is skipped by design (not treated as failure).
- Optional manual GitHub run is defined in `.github/workflows/pr-validate.yml` with `workflow_dispatch` only.

## How to Trigger a New Feature
Input entrypoint for high-level task: task file objective section.

Git behavior for this step:
- Create the new task file first and run `make task-prepare ...`.
- `task-prepare` checks out `main`, pulls latest, creates/switches `feature/issue-<id>-<slug>`, and commits the task file on that feature branch.
- `task-plan` then reuses that existing branch (no branch recreation).
- Do not commit the task file on `main` first.
- Keep tracked local changes clean before running, or branch switching can fail.

Example (UI/UX refresh):
1. Create task:
- `cp tasks/_template.md tasks/issue-103-ui-ux-refresh.md`
2. Write your high-level prompt in `## Objective`, for example:
- "Refresh dashboard UI/UX for clarity and hierarchy; improve risk card readability and mobile spacing."
3. Start workflow:
- `make task-prepare TASK=tasks/issue-103-ui-ux-refresh.md`
- `make task-plan TASK=tasks/issue-103-ui-ux-refresh.md`
4. Review generated plan and check:
- `- [x] Approved for implementation`
5. Continue:
- `make task-build TASK=tasks/issue-103-ui-ux-refresh.md`
- `make task-review TASK=tasks/issue-103-ui-ux-refresh.md`
- `make task-ship TASK=tasks/issue-103-ui-ux-refresh.md`

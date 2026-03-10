# Issue 107: Pipeline Hardening

## Objective
Improve the local AI orchestration pipeline (Mac-only, no CI dependency) for:
`prepare -> plan -> build -> review -> rework -> ship`.

Context:
- Existing pipeline is in `scripts/task_flow.sh`, `Makefile`, `docs/workflows/ai-task-flow.md`, `ReadMe.md`.
- Keep all current guardrails and good practices; improve reliability, cost, and maintainability without regressions.

Goals:
1. Externalize model config:
   - Move model/version settings out of `task_flow.sh` into a versioned config file (e.g. `.ai-models.env` or `config/ai-models.properties`).
   - Script must load config with safe defaults and clear validation errors.
2. Model routing review:
   - Re-evaluate and propose best model order for plan/build/review/escalation.
   - Make routing configurable (no hardcoded model IDs in logic).
3. Context7 MCP integration:
   - Add optional Context7 usage for plan/review to fetch up-to-date docs.
   - If setup requires manual user action, output explicit steps in plan + README.
   - Must fail gracefully when MCP is unavailable.
4. Prompt caching + compaction:
   - Implement deterministic prompt compaction for plan/review (remove redundant context, keep critical constraints).
   - Add prompt/result caching keyed by stable hash + model + task file + git state.
   - Cache must be safe (no stale reuse across relevant code/task changes).
   - Document tradeoffs and safeguards to avoid accuracy loss.
5. Reliability hardening:
   - No blind retries: failed verification should include targeted fix loop (preserve this behavior).
   - Keep branch safety, immutable plan guard, retry caps, staged review requirements.
6. Documentation:
   - Update `ReadMe.md`, `docs/workflows/ai-task-flow.md`, and any other affected docs.
   - Add a short “How config works”, “How cache works”, and “How to disable/tune”.

Non-negotiable constraints:
- Local-first on Mac.
- No destructive git actions.
- No regression of existing working flow.
- Keep command UX simple (`make task-* TASK=...`).
- Backward compatibility where feasible.

Deliverables in task file:
- Clear architecture decisions and tradeoffs.
- Exact file-by-file change plan.
- Acceptance criteria and verification checklist.
- Rollback plan.
- Copy/paste workflow commands for this task file.


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
- [ ] Implement backend changes (if required)
- [ ] Implement frontend changes (if required)
- [ ] Add/update tests
- [ ] Run verification commands

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

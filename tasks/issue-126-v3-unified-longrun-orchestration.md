# Issue 126: V3 Unified Long-Run Orchestration (Copilot + Codex)

## Objective
- Replace brittle multi-hop v2 flow with a stable v3 flow optimized for low request count and deterministic safety.
- Support both execution backends interchangeably: GitHub Copilot premium models and OpenAI Codex, selected via `.ai-models.env`.
- Make one long-running premium model session do plan + implementation + semantic self-check, then enforce deterministic gates before ship/PR.

## Architecture Decisions
- Decision 1: Keep orchestration as the single source of truth for safety/hygiene; prompts and agent instructions are advisory, not enforcement.
- Decision 2: Collapse LLM-heavy stages into one `agent_run` stage (single long-running session per attempt), followed by deterministic gate stages.
- Decision 3: Keep `prepare` and `ship` deterministic and provider-agnostic (git hygiene, branch policy, push/PR behavior).
- Decision 4: Introduce a provider adapter contract (`copilot` and `codex`) so the same pipeline can switch by config with no graph changes.
- Decision 5: Human review moves post-PR by default; pre-ship human gates only for explicit high-risk safety violations.
- Decision 6: Out-of-scope file changes are allowed only when each file is explicitly recorded in task markdown with a concrete reason; restricted paths (for example `.gitignore`, fixtures, secrets/config artifacts) are hard-fail.
- Decision 7: Deterministic gates (lint/typecheck/tests/e2e/api-smoke/secrets/scope checks) are mandatory and non-negotiable before ship/PR.
- Decision 8: Retry policy is failure-aware and non-blind: classify failure cause, apply targeted mitigation/fix first, then rerun only impacted command families.
- Decision 9: All long-running model executions are wrapped with caffeinate support so sessions are not dropped by host sleep.

## Acceptance Criteria
- [ ] V3 introduces a new workflow mode (`v3`) without breaking existing `v2` commands.
- [ ] One long-running model session executes plan + code + semantic self-check in a single provider request/session attempt.
- [ ] A structured implementation report is emitted by the long-run session and persisted into task markdown.
- [ ] Deterministic safety gates run after `agent_run` and block ship on failure with actionable diagnostics.
- [ ] Provider adapter supports at least:
- [ ] `copilot` backend (premium-request aware)
- [ ] `codex` backend (OpenAI subscription/Codex CLI flow)
- [ ] `.ai-models.env` can switch provider/model without code edits.
- [ ] Branch hygiene remains enforced:
- [ ] Never ship from `main`
- [ ] Always push feature branch
- [ ] Optional PR creation policy preserved
- [ ] Secret safety remains enforced:
- [ ] `.gitignore` changes flagged by policy
- [ ] obvious credential patterns block ship
- [ ] Human review is post-PR by default, with optional pre-ship gate only on high-risk policy events.
- [ ] Out-of-scope changed files are surfaced in task markdown with per-file reasons before ship.
- [ ] Restricted file/path changes (e.g. `.gitignore`, fixture-only artifacts, obvious secret-bearing files) hard-fail pre-ship.
- [ ] Retry behavior is failure-aware (no blind retries): reason classification, targeted fix/mitigation, then scoped rerun.
- [ ] Caffeinate wrapper is applied to long-running model sessions for both providers where supported.
- [ ] Task markdown clearly reports:
- [ ] current stage
- [ ] blocked reason
- [ ] next action
- [ ] deterministic gate results
- [ ] extra files changed + rationale
- [ ] permanently failed/gave-up reason + mitigation guidance
- [ ] Pipeline supports deterministic fallback when premium model is unavailable/exhausted.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Define v3 state machine and routing
- [x] Add provider adapter abstraction and config contract
- [x] Implement `agent_run` stage contract (single long-running request/session)
- [x] Implement deterministic gate runner + policy engine integration
- [x] Update markdown rendering for clearer pipeline status and next action
- [x] Add fallback policy (provider unavailable / premium exhausted)
- [x] Preserve branch/PR safety and shipping guarantees
- [x] Add/update tests (unit + mocked e2e orchestration)
- [x] Add migration/rollout docs for switching v2 -> v3

## V3 Design Plan

### 1) Target Workflow (Default Path)
1. `prepare` (deterministic)
- verify clean worktree (except task file and approved aux files)
- checkout/update feature branch from base
- ensure task file exists/markers valid

2. `agent_run` (single long-running premium session)
- agent does:
  - implementation plan generation
  - code changes
  - semantic self-check against acceptance criteria
  - writes structured run output for orchestration
- no intermediary plan approval gate
- no separate agent review model call on happy path

3. `deterministic_gates` (non-LLM)
- run required commands (lint/typecheck/build/tests/smoke/e2e as configured)
- run safety policy checks:
  - changed file scope policy
  - out-of-scope file rationale capture (must include reason in task markdown)
  - secret scan policy
  - restricted-file policy (e.g., `.gitignore`, fixtures, auth critical files)
- on failure: stop and emit exact failure reason + next step

4. `ship`
- ensure not on base branch
- ensure gates pass and no unresolved blockers
- commit task file + staged changes
- push feature branch
- create PR if enabled

5. `post_pr_human_review` (out-of-band)
- human review is expected on PR, not a blocking pre-ship stage by default

### 2) Exceptional Paths
- `agent_run` fails to return parseable structured output:
  - one deterministic “repair extraction” attempt
  - if still invalid, workflow blocked with raw output pointer
- deterministic gates fail:
  - fail workflow with actionable diagnostics
  - classify failure cause:
    - code defect
    - missing tool/dependency
    - infra/access issue
    - policy violation
  - apply targeted remediation first (fix code, install/enable tool, workaround for access), then rerun only impacted commands
  - optional `AUTO_FIX_MODE`:
    - `deterministic_only` (default): no extra LLM calls
    - `single_repair_session`: exactly one additional `agent_run` session
- high-risk policy violation:
  - block ship
  - optionally require explicit human override decision

### 3) Provider Adapter Contract
Define a unified provider interface:
- `start_longrun_session(prompt, repo_root, model, timeout) -> ProviderRunResult`
- `ProviderRunResult` includes:
  - `raw_output`
  - `structured_payload`
  - `session_id` / `trace_ref`
  - `status`
  - `provider_diagnostics`

Backends:
- `CopilotProviderAdapter`
- `CodexProviderAdapter`

Switching:
- `.ai-models.env` controls:
  - `V3_PROVIDER=copilot|codex`
  - `V3_MODEL=<model-name>`
  - `V3_MODE=single_session`
  - `V3_ON_PROVIDER_FAILURE=fail` (explicit mode switch by operator, no auto cross-provider fallback)

### 4) Structured Output Contract for `agent_run`
`agent_run` must return strict JSON with at least:
- `summary`
- `plan`
- `acceptance_criteria_checks` (criterion -> pass/fail/evidence)
- `changed_files`
- `notes`
- `risk_flags` (optional)

This output is machine-validated before deterministic gates.

### 5) Safety/Hygiene in Orchestration (Not in Agent Prompt)
Implement policy checks as deterministic code:
- path scope policy (planned + allowed support paths)
- sensitive file policy:
  - `.gitignore`
  - auth/security-critical modules
  - deployment/workflow files
- secret detection policy:
  - high-confidence token/key patterns
  - private key signatures
- branch policy:
  - refuse ship from base branch
- commit/push policy:
  - no auto-merge to `main`

### 6) State & Markdown Rendering Improvements
Task markdown must always show:
- `Current Stage`
- `Workflow Status`
- `Blocked Reason` (explicit)
- `Next Expected Action` (explicit command/human action)
- `Gate Results` summary with failed commands and log paths
- `Provider` and `Model` used for current run
- `Extra Files Changed` with a per-file reason (why each out-of-scope file was necessary)
- `Permanently Failed / Gave Up` with:
  - concrete stop reason
  - attempted mitigations
  - recommended next human action

### 7) Config Model (`.ai-models.env`) Additions
Add v3-specific keys:
- `PIPELINE_VERSION=v2|v3`
- `V3_PROVIDER=copilot|codex`
- `V3_MODEL=...`
- `V3_LONGRUN_TIMEOUT_MINUTES=...`
- `V3_AUTO_FIX_MODE=deterministic_only|single_repair_session`
- `V3_ENABLE_POST_PR_HUMAN_REVIEW=1`
- `V3_REQUIRE_PRE_SHIP_HUMAN_ON_HIGH_RISK=1`
- `V3_ENABLE_CAFFEINATE=1`

## Decision Log (Locked Defaults For V3)
- `PIPELINE_VERSION=v3`
- `V3_PROVIDER=copilot` (explicit run mode; set `codex` when running directly on Codex)
- `V3_AUTO_FIX_MODE=deterministic_only`
- `V3_ENABLE_CAFFEINATE=1`
- `V3_REQUIRE_PRE_SHIP_HUMAN_ON_HIGH_RISK=1`
- `V3_ENABLE_POST_PR_HUMAN_REVIEW=1`

Retry cost semantics (authoritative):
- Deterministic retries are non-LLM operations (command reruns, local diagnostics, policy checks, environment/tool mitigation) and must not start a new model session.
- Only `agent_run` starts a premium model session.
- If `V3_AUTO_FIX_MODE=deterministic_only`, failed gates do not trigger another model run.
- If `V3_AUTO_FIX_MODE=single_repair_session`, at most one additional `agent_run` session is allowed after deterministic mitigation is exhausted.

### 8) Suggested Command UX
- `make task-v3-run TASK=... THREAD_ID=...`
- `make task-v3-status TASK=... THREAD_ID=...`
- `make task-v3-resume ...` (for blocked/retry flow)

Keep v2 commands intact during rollout.
Rationale: v3 adoption should be opt-in and reversible until stability is proven.

### 9) Test Strategy (Required)
Unit tests:
- provider selection (single-provider explicit mode)
- structured output parsing/validation
- policy engine rule outcomes
- routing transitions for happy/failure/high-risk flows

Mocked e2e orchestration tests:
- successful single-session run -> deterministic gates pass -> ship
- gate failure -> blocked with clear diagnostics
- provider failure -> blocked with clear diagnostics and no automatic provider switch
- high-risk file change -> pre-ship human gate path

Regression tests:
- ensure v2 workflow still works when `PIPELINE_VERSION=v2`

### 10) Rollout Strategy
Phase 1:
- ship v3 behind config flag (`PIPELINE_VERSION=v3`)
- internal usage only

Phase 2:
- default new issues to v3, keep v2 fallback
- monitor failure classes and request usage

Phase 3:
- deprecate plan/review/rework multi-hop v2 path once v3 stability is proven

### 11) Success Metrics
- median premium requests per issue reduced by >60%
- fewer human interrupts before PR (>80% of runs no pre-ship human gate)
- lower blocked-without-reason incidents (target: near zero)
- deterministic gate failure messages always actionable (command + reason + next step)
- out-of-scope file reason coverage at 100% (no unlabeled extra file entries)

## Risks And Mitigations
- Risk: single-session output can be malformed
- Mitigation: strict schema validation + one repair extraction attempt

- Risk: reduced explicit review stage misses quality issues
- Mitigation: keep deterministic gates strict; keep optional post-failure second session

- Risk: provider behavior differences
- Mitigation: adapter contract + backend-specific tests + explicit provider-mode selection (`V3_PROVIDER`) per run

- Risk: hidden scope drift by long session
- Mitigation: hard policy engine blocks restricted paths before ship

## Behavior After PR (Intent Not Fully Achieved)
- If PR is raised but semantic intent is only partially met, workflow marks run outcome as `partial_success` in task markdown.
- Pipeline auto-generates a follow-up issue draft with:
  - unmet acceptance criteria
  - observed behavior vs expected behavior
  - suggested mitigation path
- Auto-merge remains disabled; unresolved intent gaps are handled in follow-up before final merge decision.

## Verification Evidence (Codex Mutable)
- `.venv-orch/bin/python -m pytest orchestration/tests/test_v3_pipeline.py -q` → `8 passed`
- `.venv-orch/bin/python -m pytest orchestration/tests/test_v3_runtime_and_nodes.py -q` → `10 passed`
- `.venv-orch/bin/python -m pytest orchestration/tests/test_routing.py -q` → `23 passed`
- `.venv-orch/bin/python -m pytest orchestration/tests/test_render.py -q` → `5 passed`
- `.venv-orch/bin/python -m pytest orchestration/tests/test_cli_main.py -q` → `11 passed`
- `.venv-orch/bin/python -m pytest orchestration/tests -q` → `159 passed`
- `make orch-coverage` → `TOTAL 88%` (`3264 stmts, 381 miss`)

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running rework/resume commands, add cycle-specific human guidance if needed._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

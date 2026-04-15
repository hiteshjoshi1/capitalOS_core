# CapitalOS Code Generation Pipeline State

## Purpose

This document captures the current state of the coding pipeline across all generations:

1. Legacy bash pipeline (`scripts/task_flow.sh`)
2. LangGraph v2 staged pipeline
3. LangGraph v3 unified pipeline

The goal is to create an evidence-based baseline for making v3 the default and retiring older orchestration paths.

---

## Executive Summary

- Three orchestration paradigms currently coexist in code/history context (bash, v2, v3-style unified), which increases operational and debugging overhead.
- The current unified pipeline has the right architecture direction (single implementation run + deterministic verification authority), but reliability gaps still cause frequent blocks.
- The most common blocking patterns seen in real runs are:
  - malformed/invalid structured output from provider sessions
  - changed-files integrity mismatch
  - deterministic gate failures (`api-smoke`, `test-backend`)
  - semantic-intent contract mismatch (`semantic_intent_achieved=false`)
- v3 can become the defacto pipeline, but only after contract hardening and environment preflight are stabilized.

---

## Pipeline Lineage

## 1) Legacy Bash Pipeline (v0)

### Implementation

- Entry point: `scripts/task_flow.sh`
- Stage model: `prepare -> plan -> build -> review -> review-input -> rework -> ship`
- State medium: task markdown + git state + shell checks.

### Key Capabilities

- End-to-end flow with explicit stage commands in one script.
- Strong guardrails around task markdown markers:
  - immutable region via `<!-- IMMUTABLE_PLAN_END -->`
  - required section checks before proceeding.
- Scoped staging and out-of-scope change checks.
- Retry plumbing (`MAX_RETRIES`) and failure logging.
- Builder auto-fix loop for verification failures.
- Optional prompt caching and Context7 integration.

### Shortcomings

- Shell-driven state is brittle and hard to reason about at scale.
- Heavy dependence on markdown parsing and placeholder conventions.
- Strict worktree checks create high friction for normal developer iteration.
- Resumability and human gating are ad hoc rather than state-native.
- Harder to produce deterministic machine-readable audit trails.

---

## 2) LangGraph v2 Pipeline (Staged)

### Implementation

- Graph and routing: `orchestration/graph.py`, `orchestration/routing.py`
- Stages:
  - `prepare -> plan -> human_approval_gate -> build -> agent_review -> escalation_review -> human_review -> rework_analysis -> rework_implementation -> ship`
- State medium: typed `PipelineState` persisted via LangGraph checkpointing.

### Key Capabilities

- Structured, typed state replaces shell/markdown as machine source of truth.
- Explicit interrupt/resume contracts for human gates.
- Rich review and rework cycles with historical context.
- Deterministic verification reruns during review.
- Scope and policy controls for changed files and out-of-scope changes.
- Export/import/restore support via orchestration CLI.

### Shortcomings

- Many model-heavy stages increase cost, latency, and variance.
- Verification is rerun in multiple stages, creating redundant execution cost.
- Rework/review state machine is powerful but operationally heavy.
- Cognitive load remains high for operators due to many stage transitions.

---

## 3) Current Unified Pipeline (v3-style)

### Implementation

- Stage flow:
  - `prepare -> agent_run -> deterministic_gates -> ship`
- Routing:
  - prepare/plan route into `agent_run` in the unified path.
- Runtime:
  - provider subprocess orchestration in `ProviderRuntimeService`
  - structured output parsing + optional repair pass for malformed output.
- Gate authority:
  - deterministic gates rerun verification suite and decide pass/fail.

### Current Strengths (What v3 gets right)

- Single-session implementation model reduces stage handoff complexity.
- Deterministic verification is explicit and authoritative.
- Clear hard-gate split:
  - `agent_run` enforces output integrity contracts.
  - `deterministic_gates` enforces real verification and policy.
- Policy enforcement includes:
  - restricted path checks
  - out-of-scope file reason requirements
  - secret-pattern scanning
- High-risk findings can require explicit human pre-ship approval.

### Default-Suite Verification in v3

Deterministic gates run the full default suite, not a changed-files subset:

- Backend: `make api-rebuild`, `make contract-backend`, `make test-backend`, `make api-smoke`
- Frontend: `make lint`, `make typecheck`, `make contract-frontend`, `make test-frontend`, `make e2e` (if configured)
- Pipeline: `make orch-test`

This is the correct authority model for reliable ship decisions.

---

## Real Failure Modes Observed in v3 Runs

Below are failure modes observed from issue artifacts and workflow exports (`tasks/issue-13x*.md`, `.task-flow/exports/issue-13x.json`).

## A) Structured Output Contract Failure (Provider -> JSON)

### Evidence

- `issue-130` task log: blocked with “V3 agent run failed before producing valid structured output.”
- `.task-flow/exports/issue-130-r2.json`: provider failure reason includes “Model did not return valid JSON...”

### Impact

- Long model session work may complete, but pipeline cannot continue without valid structured payload.
- Deterministic gates never run when this fails.

---

## B) Changed-Files Integrity Mismatch

### Evidence

- `issue-131`: reported changed files did not match actual git diff (task file delta mismatch included).
- `issue-137`: reported changed files, but actual diff was `['<none>']`.

### Impact

- Historically this blocked `agent_run`.
- In current implementation, mismatch is warning-only; restricted-file policy and deterministic gates are the blocking authority.
- Still causes operator confusion when model-reported edits differ from actual git state.

---

## C) Model-Reported Verification Coverage Mismatch (Historical v3 Failure Pattern)

### Evidence

- `issue-131` and `issue-132` logs include:
  - “agent_run did not report running all required relevant verification commands...”

### Impact

- Previously caused early hard-blocks before deterministic verification could run.

### Current Status

- Code now treats missing/partial `verification_commands_run` as non-blocking warning in `agent_run`.
- Deterministic gates are now the authoritative pass/fail stage.

---

## D) Deterministic Gate Failures on Real Verification

### Evidence

- `.task-flow/exports/issue-136.json`: blocked reason `Deterministic gates failed: api-smoke`
- `.task-flow/exports/issue-137.json`: blocked reason `Deterministic gates failed: test-backend`

### Impact

- Correct behavior: pipeline blocks on actual failing checks.
- Exposes environment/test consistency gaps between model run and deterministic rerun.

---

## E) Semantic-Intent Contract Failure

### Evidence

- `issue-138` machine-rendered log: blocked reason `Agent run reported semantic intent not achieved.`

### Impact

- Even with substantial implementation work, pipeline blocks if semantic intent is explicitly reported as unmet.
- This is structurally valid, but can produce perceived false negatives if prompt/contract interpretation is inconsistent.

---

## F) Environment and Infra Mismatch During Gates

### Evidence

- `issue-138` notes include verification blockage with docker/socket environment-related failure context.

### Impact

- Deterministic gates fail for infrastructure conditions unrelated to code logic.
- Reduces trust in “all green means ready” unless preflight is stable.

---

## Why v3 Still Feels Brittle

v3’s architecture is directionally correct, but failures cluster at contract boundaries:

1. **Provider output contract boundary**
   - Long session returns non-parseable output.
2. **Repo integrity boundary**
   - Reported `changed_files` diverges from git-observed diff.
3. **Execution environment boundary**
   - Deterministic suite reruns in conditions that differ from agent assumptions.
4. **Semantic completion boundary**
   - Implementation may be substantial, but self-reported semantic completion blocks pipeline.

These are not “single bug” failures; they are boundary-hardening gaps.

---

## Capability vs Reliability Matrix (Current)

| Pipeline | Delivery Capability | Determinism | Operator Friction | Reliability |
|---|---|---|---|---|
| Bash (v0) | Medium | Medium-Low | High | Medium-Low |
| LangGraph v2 | High | Medium-High | High | Medium |
| LangGraph v3 | High (when successful) | High at gates | Medium | Medium-Low today |

Interpretation:
- v3 has highest long-term ceiling.
- v3 reliability still trails its intended architecture benefits.

---

## What Must Be True Before Retiring Older Pipelines

To make v3 defacto and remove older LangGraph/baseline paths safely:

1. **Unified pipeline docs must stay accurate**
   - remove stale operator references that imply old staged defaults.
2. **Provider output contract must be hardened**
   - malformed output must be rare and recoverable.
3. **Changed-files contract must be robust**
   - avoid false mismatch blocks for pipeline-managed task-file edits.
4. **Deterministic preflight must be explicit**
   - ensure environment prerequisites before full gate suite.
5. **Failure classification must be operator-usable**
   - clear separation: code failure vs infra failure vs contract failure.
6. **Deprecation plan**
   - freeze bash/v2 for new issues, then remove after stability window.

---

## Recommended Decommission Path

### Phase 1: Stabilize v3 (No removal yet)

- Keep v2 and bash available as fallback.
- Track v3 run outcomes by failure category:
  - provider-output
  - changed-files-integrity
  - deterministic-code-failure
  - deterministic-infra-failure
  - semantic-intent-failure

### Phase 2: Complete Defacto Migration

- Keep unified flow as standard operator path.
- Continue updating operator docs/commands (`task-run`, `task-status`, `task-resume`) as canonical references.
- Keep v2 only for emergency/manual recovery.

### Phase 3: Retire Legacy Paths

- Remove bash pipeline from normal documentation.
- Remove v2 orchestration stage entrypoints from routine workflow.
- Keep only migration/forensics docs for historical reference.

---

## Final Assessment

- v3 is the correct long-term architecture.
- Current failures are mostly boundary reliability issues, not fundamental design mismatch.
- The immediate priority is not new pipeline versions; it is hardening v3 contracts and preflight behavior so deterministic gates represent trustworthy final authority.

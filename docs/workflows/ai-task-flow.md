# CapitalOS AI Task Flow

This is the authoritative operator guide for the current orchestration pipeline.

## Current Implementation (Unified)

The pipeline is unified and v3-style by default.

Primary flow:

```text
prepare
  -> agent_run
  -> deterministic_gates
  -> waiting_for_human
  -> ship (manual trigger)
```

Notes:

- `pipeline_version` is effectively `v3` in runtime initialization.
- Deterministic gates are the final authority for verification pass/fail.
- Shipping is intentionally manual (`make task-ship`) after gates pass.

---

## Core Commands

## Run the workflow

```bash
make task-run TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

This runs from `prepare` through `deterministic_gates`.

## Check status / export summary

```bash
make task-status TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

## Resume a waiting gate

```bash
make task-resume TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='...'
```

## Ship after gates pass

```bash
make task-ship TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

## Interactive gate response

```bash
make task-respond TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

## State tools

```bash
make task-export-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-import-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 STATE_FILE=.task-flow/exports/issue-123.json
make task-restore-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123-restored STATE_FILE=.task-flow/exports/issue-123.json RESTART_AT=agent_run
```

## Orchestration tests

```bash
make task-orch-smoke
make orch-test
```

---

## Provider Configuration

Use `.env` / `.ai-models.env`:

- `PROVIDER=copilot|codex`
- `MODEL=<model-name>`
- `LONGRUN_TIMEOUT_MINUTES=<int>`
- `INACTIVITY_TIMEOUT_MINUTES=<int>`
- `REPAIR_ENABLED=0|1`
- `ENABLE_CAFFEINATE=0|1`
- `REQUIRE_PRE_SHIP_HUMAN_ON_HIGH_RISK=0|1`

Backward-compatible `V3_*` env names are still accepted.

---

## Gate Semantics

## `agent_run`

What it does:

- runs single-session implementation through selected provider
- expects strict structured JSON output
- stores actual git changed files as source of truth

Hard blockers:

- restricted file/path modifications (for example `.env`, `.gitignore`, `.task-flow/`, `data/fixtures/`)
- semantic contradiction: `semantic_intent_achieved=true` with non-empty `unresolved_failures`
- provider/runtime hard failure (subprocess failure/stall or malformed structured output unrecoverable by repair)

Non-blocking warnings:

- mismatch between model-reported `changed_files` and actual git diff
- missing/partial `verification_commands_run` report from model

## `deterministic_gates`

What it does:

- reruns deterministic verification suite
- applies scope/policy checks
- blocks if semantic intent is not achieved

Default verification suite:

- backend: `make api-rebuild`, `make contract-backend`, `make test-backend`, `make api-smoke`
- frontend: `make lint`, `make typecheck`, `make contract-frontend`, `make test-frontend`, `make e2e` (if configured)
- pipeline: `make orch-test`

Outcomes:

- pass: workflow moves to `waiting_for_human`
- fail: workflow status becomes `blocked`

If high-risk flags exist and high-risk pre-ship review is enabled, a human gate is required before continue.

---

## Standard Operator Flow

1. Create/update task file:

```bash
cp tasks/_template.md tasks/issue-123-my-feature.md
```

2. Run:

```bash
make task-run TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

3. Inspect status:

```bash
make task-status TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

4. If waiting on high-risk gate, resume with decision.
5. When `deterministic_gates` is green and workflow is waiting for human, ship:

```bash
make task-ship TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

---

## Resume Payload Examples

## High-risk review approved

```json
{
  "gate_type": "v3_high_risk_review",
  "decision": "approved",
  "reviewer": "Hitesh",
  "notes": "Reviewed and approved"
}
```

## High-risk review needs fixes

```json
{
  "gate_type": "v3_high_risk_review",
  "decision": "needs_fixes",
  "reviewer": "Hitesh",
  "notes": "Risk remains too high; address findings"
}
```

---

## Legacy Command Notes

These legacy commands no longer represent the canonical operator path:

- `task-v3-run`
- `task-v3-status`
- `task-v3-resume`

Use:

- `task-run`
- `task-status`
- `task-resume`

Legacy staged commands (`task-plan`, `task-build`, `task-agent-review`, `task-rework`) still exist, but unified execution should be treated as standard operating mode unless explicitly debugging internals.


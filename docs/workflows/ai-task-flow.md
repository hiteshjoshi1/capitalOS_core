# CapitalOS AI Task Flow

This document is the authoritative operator guide for implementing features using the CapitalOS AI orchestration pipeline.

It explains:

- the pipeline architecture
- the exact step-by-step operator flow from new task to ship
- the canonical Make commands
- the JSON payloads for human resume points
- export / import / restore flows
- how to test the pipeline

---

## Purpose

The CapitalOS AI task flow is designed to support local-first, resumable, human-gated feature delivery.

The workflow is:

- local-first
- branch-safe
- resumable
- explicit about human approvals
- based on structured state rather than markdown parsing

---

## Workflow Versions

Both versions are supported. v2 documentation in this file remains valid.

- `PIPELINE_VERSION=v2` (default): staged plan/build/review/rework workflow.
- `PIPELINE_VERSION=v3`: unified long-run session + deterministic gates.

v3 is optimized for premium-request budgets by collapsing model-heavy work into one `agent_run` session per attempt.

---

## Core Architecture

The workflow is implemented in Python under `orchestration/` using:

- **LangGraph** for orchestration, routing, interrupts, checkpoints, and resumability
- **Pydantic** for typed shared state and stage outputs

### Core design rules

#### 1. Structured state is the machine source of truth
Workflow decisions and transitions are driven by typed structured state.

Examples include:

- issue metadata
- current stage
- workflow status
- plan output
- build output
- verification evidence
- review cycles
- rework cycles
- ship result

#### 2. Markdown is a human-facing artifact
Task markdown files remain important, but they are not the workflow database.

Task files are used for:

- human-authored issue definition
- objective and acceptance criteria
- human-readable execution journal rendered from structured state

#### 3. Human approvals are explicit graph interrupts
The workflow pauses at human gates and resumes with structured JSON payloads.

Primary gates:

- plan approval
- human review

#### 4. Workflow intent is preserved, but shell-specific hacks are removed
The old shell pipeline used markdown parsing, placeholder blocks, and implicit state transitions.

The new workflow preserves the intent:

- prepare
- plan
- human approval
- build
- agent review
- optional escalation review
- human review
- rework loop
- ship

but implements it with explicit typed state and graph routing.

---

## High-Level Pipeline

```text
prepare
  -> plan
  -> human approval gate
  -> build
  -> agent review
  -> optional escalation review
  -> human review
  -> if approved: ship
  -> if needs fixes:
        rework analysis
        -> rework implementation
        -> agent review
        -> optional escalation review
        -> human review
        -> repeat until approved
```

## Stage Meanings

### prepare

Ensures task file exists, prepares or switches to the correct issue branch, and bootstraps workflow context for the issue.

```bash
make task-prepare TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### plan

Generates a structured implementation plan, records acceptance criteria, checklist, and planned file paths, and captures immutable plan hash.

```bash
make task-plan TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### human_approval_gate

Mandatory human gate after planning that blocks build until approved.

```bash
make task-approve-plan TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='{"decision":"approved",...}'
```

### build

Implements the feature, runs verification suite, stages scoped changes, and preserves immutable plan region.

```bash
make task-build TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### agent_review

Performs structured model review on build or rework output. May approve, request fixes, or escalate.

```bash
make task-agent-review TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### escalation_review

Second-pass review for uncertain or high-risk cases.

### human_review

Human review after agent review that can approve or request fixes.

```bash
make task-human-review TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='{"decision":"approved",...}'
```

### rework_analysis

Analyzes latest findings and human comments, and produces structured rework plan and answer matrix.

### rework_implementation

Applies the rework, reruns verification, and returns to review loop.

```bash
make task-rework TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### ship

Final guarded ship step that commits and pushes branch, and optionally opens PR.

```bash
make task-ship TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### respond

Generates structured JSON response for the current workflow state. Used internally by the pipeline to format responses at stage boundaries.

```bash
make task-respond TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

## Canonical Task File

Task files live under:

`tasks/issue-<id>-<slug>.md`

Example:

`tasks/issue-103-ui-ux-refresh.md`

## Canonical Make Commands

### Core workflow commands

```bash
make task-prepare TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-plan TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-build TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-agent-review TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-rework TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-ship TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-all TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-respond TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

### V3 commands (additive; v2 remains unchanged)

```bash
make task-v3-run TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-v3-status TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-v3-resume TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='...'
```

### V3 stage flow

```text
prepare
  -> agent_run
  -> deterministic_gates
  -> ship
```

### V3 provider mode (explicit, no fallback)

V3 runs exactly one provider per invocation. It does not auto-fallback across subscriptions.

- Copilot mode:
  - `V3_PROVIDER=copilot`
  - `V3_MODEL=<copilot-supported-model>`
- Codex mode:
  - `V3_PROVIDER=codex`
  - `V3_MODEL=<codex-supported-model>`

If the selected provider/model fails, the run is blocked and reported. Switching provider is an explicit operator choice in env, then rerun.

Failure behavior in v3:

- deterministic gate failures are classified and reported with command/log detail.
- out-of-scope files are allowed only with explicit per-file reason.
- restricted files/paths and secret-like content are hard-fail.
- optional one-time repair session is controlled by `V3_AUTO_FIX_MODE`.

### Human gate resume commands

```bash
make task-approve-plan TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='...'
make task-human-review TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='...'
make task-resume TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 RESUME_JSON='...'
```

### State and debugging commands

```bash
make task-export-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-import-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123 STATE_FILE=.task-flow/exports/issue-123.json
make task-restore-state TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123-restored STATE_FILE=.task-flow/exports/issue-123.json RESTART_AT=human_review
make task-state-show TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
make task-orch-smoke
```

## End-to-End Feature Workflow

This is the canonical operator path for implementing a new feature.

### Step 0 — Preflight

Run a quick workflow smoke test and standard verification:

```bash
make task-orch-smoke
make verify
```

If you also need the app running locally:

```bash
make up
make db-migrate
make api-up
make web-up
```

### Step 1 — Create the task file

Create a new issue task file:

```bash
cp tasks/_template.md tasks/issue-123-my-feature.md
```

Example:

```bash
cp tasks/_template.md tasks/issue-103-ui-ux-refresh.md
```
### Step 2 — Write the initial objective

Edit the task file and write the initial human problem statement.

At minimum, fill:

```
## Objective
```

If known, also fill or refine:

```
## Acceptance Criteria
```

any architecture notes or constraints

Example objective:

Refresh dashboard UI/UX for clearer hierarchy, better risk-card readability, and better mobile spacing.

Keep this high level and human-authored. The planner will refine it.

### Step 3 — Choose a stable thread id

Pick a thread id for the issue and keep using it throughout the workflow.

Example:

`issue-103`
### Step 4 — Prepare the workflow context

Run:

```bash
make task-prepare TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

What this does:

- ensures the task file exists
- prepares the issue branch
- initializes workflow context for that task

### Step 5 — Generate the plan

Run:

```bash
make task-plan TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

What happens:

- planner reads the task markdown as human context
- produces structured PlanOutput
- records:
  - plan summary
  - architecture decisions
  - risks
  - acceptance criteria
  - checklist
  - planned paths
- captures immutable plan hash
- renders the plan summary into the task markdown

At this point the workflow has not started implementation.

### Step 6 — Review the generated plan as a human

Open the task file and review:

- objective clarity
- architecture choices
- scope boundaries
- acceptance criteria
- checklist sanity
- planned paths

Questions to ask:

- Is the scope too broad?
- Are the acceptance criteria testable?
- Are the planned files reasonable?
- Is anything missing?
- Would I approve this if a human engineer proposed it?

### Step 7 — Approve or reject the plan

#### Approve the plan

```bash
make task-approve-plan \
  TASK=tasks/issue-103-ui-ux-refresh.md \
  THREAD_ID=issue-103 \
  RESUME_JSON='{"gate_type":"plan_approval","decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'
```

#### Reject or request fixes to the plan

```bash
make task-approve-plan \
  TASK=tasks/issue-103-ui-ux-refresh.md \
  THREAD_ID=issue-103 \
  RESUME_JSON='{"gate_type":"plan_approval","decision":"needs_fixes","reviewer":"Hitesh","notes":"Scope is too broad; narrow to dashboard cards only","questions":["Can this be split into two tasks?"],"response_requirements":["Reduce scope and tighten acceptance criteria"],"unresolved_comments":["Do not touch unrelated layout areas"]}'
```

If you reject, the workflow should not proceed into build until the plan is corrected.

### Step 8 — Build the feature

If running stepwise:

```bash
make task-build TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

If running full workflow, task-all will continue after plan approval.

What happens during build:

- immutable plan region is checked
- builder implements the feature
- verification suite runs
- retry policy is applied
- one scoped builder auto-fix pass may be attempted on repeated code failures
- changed files are staged if within allowed scope
- markdown execution journal is updated

Typical verification includes:

```bash
make lint
make typecheck
make test-backend
make test-frontend
make api-smoke
make e2e   # if Playwright is configured
```

### Step 9 — Run agent review

Run:

```bash
make task-agent-review TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

Possible outcomes:

- approved
- needs_fixes
- escalate

If the review is high-risk or uncertain, the graph may route into escalation review during full workflow execution.

### Step 10 — Complete human review

When the workflow pauses for human review, inspect:

- rendered review cycle in task markdown
- summary of findings
- test gaps
- changed files
- verification outcome

verification outcome

Then resume the human review gate.

#### Approve

```bash
make task-human-review \
  TASK=tasks/issue-103-ui-ux-refresh.md \
  THREAD_ID=issue-103 \
  RESUME_JSON='{"decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'
```

#### Request fixes

```bash
make task-human-review \
  TASK=tasks/issue-103-ui-ux-refresh.md \
  THREAD_ID=issue-103 \
  RESUME_JSON='{"decision":"needs_fixes","reviewer":"Hitesh","notes":"Please fix the routing edge case and make the acceptance criteria coverage clearer","questions":["Was the edge case tested?"],"response_requirements":["Show the exact fix and verification evidence"],"unresolved_comments":["Do not ship until this is corrected"]}'
```

If both:

- effective agent review = approved
- human review = approved

then the workflow can ship.

If either requests fixes, the workflow enters rework.

### Step 11 — Rework loop

If human or agent review requests fixes, the workflow goes through:

- rework_analysis
- rework_implementation
- review again

You can trigger rework directly if operating manually:

```bash
make task-rework TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

#### Rework analysis

Produces:

- root cause
- findings addressed
- planned changes
- validation plan
- answer matrix

#### Rework implementation

Applies the changes and reruns verification.

Then the workflow returns to:

- agent review
- optional escalation review
- human review

This loop continues until both sides approve.

### Step 12 — Ship

Once the final review cycle is approved and blockers are clear:

```bash
make task-ship TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

What happens:

- final ship checks run
- branch is pushed
- PR may be created if enabled in orchestration config

## Fast Path (Recommended for normal usage)

The simplest operator path is:

1. Create the task file

```bash
cp tasks/_template.md tasks/issue-123-my-feature.md
```

2. Write the objective

Edit the file.

3. Start the full workflow

```bash
make task-all TASK=tasks/issue-123-my-feature.md THREAD_ID=issue-123
```

4. Approve the plan when interrupted

```bash
make task-approve-plan \
  TASK=tasks/issue-123-my-feature.md \
  THREAD_ID=issue-123 \
  RESUME_JSON='{"gate_type":"plan_approval","decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'
```

5. Approve or reject human review when interrupted

Approve:

```bash
make task-human-review \
  TASK=tasks/issue-123-my-feature.md \
  THREAD_ID=issue-123 \
  RESUME_JSON='{"decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'
```

Or request fixes:

```bash
make task-human-review \
  TASK=tasks/issue-123-my-feature.md \
  THREAD_ID=issue-123 \
  RESUME_JSON='{"decision":"needs_fixes","reviewer":"Hitesh","notes":"Please address the routing issue","questions":["Was the edge case covered?"],"response_requirements":["Show the exact routing fix"],"unresolved_comments":["Do not ship until corrected"]}'
```

If you reject with needs_fixes, the workflow continues through rework and returns to human review again.

## JSON Resume Payload Examples

### Plan approval — approved

```json
{
  "gate_type": "plan_approval",
  "decision": "approved",
  "reviewer": "Hitesh",
  "notes": "Looks good",
  "questions": [],
  "response_requirements": [],
  "unresolved_comments": []
}
```

### Plan approval — needs fixes

```json
{
  "gate_type": "plan_approval",
  "decision": "needs_fixes",
  "reviewer": "Hitesh",
  "notes": "Scope too broad",
  "questions": ["Split task?"],
  "response_requirements": ["Reduce scope"],
  "unresolved_comments": ["Do not touch unrelated modules"]
}
```

### Human review — approved

```json
{
  "decision": "approved",
  "reviewer": "Hitesh",
  "notes": "Looks good",
  "questions": [],
  "response_requirements": [],
  "unresolved_comments": []
}
```

### Human review — needs fixes

```json
{
  "decision": "needs_fixes",
  "reviewer": "Hitesh",
  "notes": "Fix edge case",
  "questions": ["Was it tested?"],
  "response_requirements": ["Show fix"],
  "unresolved_comments": ["Do not ship"]
}
```

## State Export, Import, and Restore

### Export current workflow state

```bash
make task-export-state TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103
```

### Inspect exported state

```bash
make task-import-state TASK=tasks/issue-103-ui-ux-refresh.md THREAD_ID=issue-103 STATE_FILE=.task-flow/exports/issue-103.json
```

### Restore into a new thread

```bash
make task-restore-state \
  TASK=tasks/issue-103-ui-ux-refresh.md \
  THREAD_ID=issue-103-restored \
  STATE_FILE=.task-flow/exports/issue-103.json \
  RESTART_AT=human_review
```

### When to use restore

Use restore when:

- checkpoint DB is lost or corrupted

- moving machines or environments

- graph or state schema changed and you want a clean restart point

- you want to branch from an earlier workflow snapshot

- you need to recover from bad human input

## Testing the Pipeline

There are two useful layers of testing.

1. Quick orchestration smoke test

```bash
make task-orch-smoke
```

2. Full orchestration test suite

Run:

```bash
pytest orchestration/tests -q
```

### Useful individual tests

```bash
pytest orchestration/tests/test_routing.py -q
pytest orchestration/tests/test_state_machine.py -q
pytest orchestration/tests/test_integrity.py -q
pytest orchestration/tests/test_e2e_mocked.py -q
pytest orchestration/tests/test_escalation_rework_ship.py -q
```

These tests validate workflow logic without requiring live model calls.

## Guardrails

The workflow is designed to enforce these rules:

- structured state is authoritative
- human approval is mandatory before build
- immutable plan region must not change during mutable stages
- verification is required before approval and ship
- out-of-scope changes are blocked
- ship is blocked if blockers remain
- workflow should never intentionally ship from base branch
- markdown is rendered from state rather than reparsed as the primary workflow database

## Practical Advice

If you are implementing a real feature, do this:

- create the task file
- write a clear objective and constraints
- run task-all
- inspect the generated plan carefully
- only approve the plan if you would approve it from a human engineer
- during human review, push hard on:
  - scope creep
  - weak verification
  - unclear evidence
  - unnecessary refactors
- only ship once findings are actually closed, not just summarized nicely

The quality of the workflow depends more on discipline than on model choice.

# Issue 132: AI Sage Company Thesis Mode

## Objective
- Deliver the second high-value mode as fast as possible:
  `Company Thesis Mode`
- Support prompts like:
  - "Here is my thesis on Tencent Music. Pressure test it."
  - "What would Buffett and Nick Sleep worry about here?"
  - "What are the missing questions and weak points in this thesis?"
- Combine:
  - author wisdom
  - live company research
  - structured synthesis
  - critique
  - an updated thesis view

## Program Position
- Depends on issue 130 and issue 131.
- This is the second step in the ruthless build order:
  1. concept mode
  2. company thesis mode
  3. research memory
- Treat issue 131 as the baseline already delivered:
  - single-input `AI Sage`
  - chat-style question/answer flow
  - corpus-backed concept answers
  - distinct author perspectives
  - synthesis, critique, and inspectable sources
- This issue should extend that baseline into company-thesis pressure testing, not replace it with a different UI or expose internal controls again.

## Central Product Idea
- Company thesis mode should feel like intelligent pushback, not just company summarization.
- The system should:
  - identify the thesis claims being made
  - pull relevant author lenses
  - surface missing questions and blind spots
  - fetch live company evidence
  - answer what it can from fetched evidence
  - synthesize what strengthens vs weakens the thesis
  - critique the current view

## User Intent
- The user already has a view, partial thesis, or instinct about a company.
- The user is not asking for a generic company explainer.
- The user wants:
  - sharper pushback
  - missing questions surfaced
  - relevant author lenses
  - live facts that matter to the thesis
  - a clearer view of what got stronger vs weaker

## Primary User Experience
- The user stays in the same `AI Sage` chat flow introduced in issue 131.
- The user pastes a thesis, question, or concern in plain language.
- The system should decide that this is a company-thesis prompt and do the work behind the scenes.
- The user should not have to choose:
  - company mode
  - research mode
  - author ids
  - retrieval settings
  - web-search toggles

## UX Behavior
- The answer should read like one coherent assistant response in the chat thread.
- The assistant response should lead with the pressure-tested answer, not with metadata.
- Supporting sections should appear under that answer in a clear order:
  1. thesis / question
  2. key pushback questions
  3. missing information
  4. key facts extracted
  5. author views
  6. synthesis
  7. critique
  8. updated thesis view
  9. fetched sources used
- Source detail should be inspectable and attributable, but not overwhelm first paint.

## Research Behavior
- Use live company / web research when it materially improves the answer.
- That includes cases where:
  - the internal corpus is not enough
  - the answer depends on current company facts
  - the answer would materially benefit from fresh filings, transcripts, reports, or web evidence
- If the system surfaces new follow-up questions during reasoning, do not recursively research them by default.
- Instead:
  - show those follow-up questions to the user
  - let the user decide whether to continue

## What Good Looks Like
- A strong answer feels like intelligent pressure testing, not a prettified summary.
- The pushback questions should be genuinely useful and non-obvious.
- The fetched facts should change or sharpen the answer, not just decorate it.
- The author views should frame the thesis differently, not repeat one blended opinion.
- The updated thesis view should clearly separate:
  - what looks stronger now
  - what looks weaker now
  - what remains unresolved

## Scope
- Thesis-oriented query handling
- Extraction of thesis claims / assumptions from user input
- Key pushback questions
- Missing information detection
- Author perspectives
- Live evidence from filings, transcripts, reports, and web research
- Synthesis and critique
- Updated thesis view in the output

## Out Of Scope
- Save/retrieve research memory
- Full memo workflow
- Outcome review / calibration
- Portfolio monitoring
- Autonomous recommendations
- New UI mode-switchers or exposed internal controls
- Recursive autonomous research on follow-up questions surfaced by the system

## Acceptance Criteria
- [ ] `AI Sage` can accept a thesis-style company prompt and classify it into company thesis mode.
- [ ] For a company thesis query, the system returns:
  - thesis / question
  - key pushback questions
  - missing information
  - key facts extracted
  - author views
  - synthesis
  - critique
  - updated thesis view
  - fetched sources used
- [ ] Live company research materially improves the answer when internal corpus alone is insufficient.
- [ ] Source attribution clearly distinguishes:
  - thinker corpus evidence
  - fetched company / web evidence
- [ ] If the system surfaces additional follow-up questions, it does not recursively research them by default; it shows them to the user first.
- [ ] Add backend tests for:
  - thesis classification
  - live research fetch/routing
  - source attribution
  - synthesis/critique response shape
- [ ] Add frontend tests for thesis-mode rendering.

## Product Guardrails
- Do not regress the simple chat-style `AI Sage` experience from issue 131.
- Do not turn company thesis mode into a generic “company overview” answer.
- Do not lead with author metadata, scorecards, or internal routing details.
- Do not fetch extra sources just because they exist; fetch only what sharpens the thesis answer.
- Keep asking:
  - does this improve thesis pressure testing now?
  - does this help the user think more clearly now?
  - if not, defer it.

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- `curl -X POST http://localhost:8000/ai-sage/query -H "Content-Type: application/json" -d '{"query":"Here is my thesis on Tencent Music. Pressure test it."}'`
- Verify the answer includes:
  - pushback questions
  - extracted facts
  - author perspectives
  - synthesis
  - critique
  - updated thesis view
  - live sources used

## Human Notes
- This issue should be judged by whether it surfaces non-obvious pushback and genuinely improves the user’s thesis.
- Generic “company overview” behavior is a failure even if the answer is polished.
- The main question is: does the system think with you, or just summarize what it found?

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `<stage>`
- Workflow Status: `<running|blocked|shipped|failed>`
- Provider/Model: `<provider>/<model>`
- Last Updated: `<timestamp>`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
- Next expected action: `<command or decision>`
- Open questions:
  - `<question>`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `agent_run`
**Workflow Status**: `blocked`

## Workflow Snapshot
- latest_outcome: agent_run did not report running all required relevant verification commands: make contract-backend, make lint, make typecheck, make contract-frontend, make e2e
- next_action: Inspect blockers and rerun the appropriate stage after adding new context.
- pipeline_version: `v3`
- retry_gate_pending: `no`
- blocked_reason: agent_run did not report running all required relevant verification commands: make contract-backend, make lint, make typecheck, make contract-frontend, make e2e

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-132-multi-lens-reasoning-synthesis-and-critic` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- agent_run did not report running all required relevant verification commands: make contract-backend, make lint, make typecheck, make contract-frontend, make e2e

## Permanently Failed / Gave Up
- Stop reason: agent_run did not report running all required relevant verification commands: make contract-backend, make lint, make typecheck, make contract-frontend, make e2e
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->

# Issue 131: AI Sage Concept Mode

## Objective
- Deliver the first real user value for Module 2 as fast as possible.
- Build `Concept Mode` in `AI Sage`: a single-input experience for questions like:
  - "What makes a good business?"
  - "How should I think about moat, scale economies shared, or network effects?"
- Return a materially better answer than generic chat by combining:
  - relevant author passages
  - distinct author perspectives
  - one synthesis
  - one critique
  - suggested original readings

## Program Position
- Depends on issue 130 retrieval, author selection, and author wisdom.
- This is the first issue in the ruthless build order:
  1. concept mode
  2. company thesis mode
  3. research memory
- Everything else should defer unless it clearly improves answer quality for concept mode now.

## Central Product Idea
- `AI Sage` is a thinking workbench, not a bag of backend modes.
- The user asks one question in plain language.
- The system decides which authors are relevant.
- The system returns differentiated author views, not one blended finance answer.
- The system then synthesizes and critiques those views.
- The system should also recommend what to read next from the author corpus.

## User Intent
- The user is not asking for a generic explainer.
- The user wants help thinking better by seeing how strong underlying thinkers would frame the concept differently.
- The user should come away with:
  - clearer mental models
  - clearer distinctions between author views
  - a synthesis that helps action or understanding
  - a critique that prevents false confidence
  - obvious next readings if they want to go deeper

## Primary User Experience
- The user opens `AI Sage` and sees one main query input.
- The user asks a concept question in natural language.
- The system does the work behind the scenes:
  - decide whether the author corpus is relevant
  - select the most relevant authors
  - retrieve the best supporting passages
  - generate distinct author views
  - generate one synthesis
  - generate one critique
- The UI should feel simple, direct, and opinionated.
- The user should never have to choose:
  - author ids
  - retrieval modes
  - reasoning modes
  - internal RAG controls

## UX Behavior
- The answer should appear as one coherent result, not as a debugging console.
- Results should be easy to scan in this order:
  1. question
  2. relevant authors
  3. best passages / evidence
  4. author views
  5. synthesis
  6. critique
  7. suggested original readings
- Evidence should be inspectable, but not noisy by default.
- The user should immediately understand:
  - which authors were used
  - why the answer is better than a generic chat response
  - where to go next if they want to read source material directly

## What Good Looks Like
- A strong answer feels grounded, differentiated, and useful.
- The author views should not collapse into one generic tone.
- The synthesis should simplify without flattening meaningful differences.
- The critique should add real pushback, not ritual pessimism.
- Suggested readings should feel like the obvious best next step, not random citations.
- A successful output should feel like:
  - "I understand this concept better now"
  - "I can see how different thinkers would frame it"
  - "I know what to read next if I want depth"

## Weak-Evidence Behavior
- If the author corpus is not strongly relevant, the system should say so clearly.
- If evidence is thin, the system should avoid pretending certainty.
- If one or two authors are useful but others are weakly matched, the system should use the useful ones and avoid forced inclusion.
- If the system cannot produce a differentiated answer that is better than generic chat, it should return a limited answer and make the weakness explicit.
- The system should not fabricate author views when the corpus grounding is weak.

## Scope
- Single-input `AI Sage` query flow for concept questions
- Automatic author selection
- Retrieval of best supporting passages
- Distinct author perspective generation
- Synthesis layer
- Critique layer
- Suggested original readings / passages to continue from
- Simple output structure in the UI and API

## Out Of Scope
- Live company/web research
- Thesis pressure-testing
- Save/retrieve research memory
- Decision memo workflows
- Calibration / outcome review
- Portfolio monitoring
- Product scaffolding that does not materially improve concept answers now
- Internal controls or UX levers that expose implementation details to the user

## Acceptance Criteria
- [ ] `AI Sage` concept queries behave as one simple user flow rather than multiple exposed system modes.
- [ ] For a concept question, the system returns:
  - question
  - relevant authors
  - best passages / evidence
  - author views
  - synthesis
  - critique
  - suggested original readings
- [ ] Author perspectives are visibly distinct rather than flattened into one voice.
- [ ] Every non-trivial answer is grounded in retrieved passages from the ingested author corpus.
- [ ] UI remains minimal:
  - one main query input
  - answer/results at the top
  - evidence inspectable on demand
  - no visible internal mode switches
- [ ] If evidence is weak or only partially relevant, the system says that clearly instead of forcing a polished but weak answer.
- [ ] Suggested readings feel like a continuation path for learning, not a dump of citations.
- [ ] Add backend tests for:
  - concept-query routing
  - author selection
  - author view generation shape
  - synthesis shape
  - critique shape
- [ ] Add frontend tests for the concept-mode rendering flow.

## Output Contract
- The answer should try to preserve this structure:
  - question
  - relevant authors
  - best passages / evidence
  - author views
  - synthesis
  - critique
  - suggested original readings
- This is a product contract, not a command to implement a specific internal schema.

## Product Guardrails
- Do not build concept mode as a generic “one answer paragraph plus citations” flow.
- Do not surface hidden system jargon like:
  - retrieve
  - ask
  - company context
  - evidence first
  - RAG research
- Do not optimize for future memo/calibration workflows in this issue.
- Keep asking:
  - does this make concept-mode answers better now?
  - does this help the user think more clearly now?
  - if not, defer it.

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- `curl -X POST http://localhost:8000/ai-sage/query -H "Content-Type: application/json" -d '{"query":"What makes a good business?"}'`
- `curl -X POST http://localhost:8000/ai-sage/query -H "Content-Type: application/json" -d '{"query":"How should I think about network effects?"}'`
- Verify `AI Sage` shows:
  - retrieved passages
  - distinct author views
  - synthesis
  - critique
  - suggested readings

## Human Notes
- This issue should be judged by answer quality, not by orchestration cleverness.
- If something does not make concept-mode answers materially better, defer it.
- A good test question is whether the answer feels clearly better than generic ChatGPT because it preserves author distinctions and cites useful original passages.
- The correct failure mode is a modest, honest, grounded answer.
- The wrong failure mode is a polished generic answer that sounds smart but teaches little.

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
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
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
- latest_outcome: agent_run did not report running all required relevant verification commands: make api-rebuild, make contract-backend, make test-backend, make api-smoke, make lint, make typecheck, make contract-frontend, make test-frontend, make e2e
- next_action: Inspect blockers and rerun the appropriate stage after adding new context.
- pipeline_version: `v3`
- retry_gate_pending: `no`
- blocked_reason: agent_run did not report running all required relevant verification commands: make api-rebuild, make contract-backend, make test-backend, make api-smoke, make lint, make typecheck, make contract-frontend, make test-frontend, make e2e

## Active Requirements
- No active requirements recorded yet.

## Prepare
Checked out `feature/issue-131-decision-copilot-memos-and-calibration` from `main` and ensured task file exists.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._

## Blockers
- agent_run reported changed_files that do not match the actual git diff. reported=['api/app/main.py', 'api/app/rag/concept_mode.py', 'api/app/routers/ai_sage.py', 'api/tests/test_ai_sage_concept.py', 'web/src/__tests__/AISage.test.tsx', 'web/src/lib/api.ts', 'web/src/routes/AISage.tsx'] actual=['api/app/main.py', 'api/app/rag/concept_mode.py', 'api/app/routers/ai_sage.py', 'api/tests/test_ai_sage_concept.py', 'tasks/issue-131-decision-copilot-memos-and-calibration.md', 'web/src/__tests__/AISage.test.tsx', 'web/src/lib/api.ts', 'web/src/routes/AISage.tsx']
- agent_run did not report running all required relevant verification commands: make api-rebuild, make contract-backend, make test-backend, make api-smoke, make lint, make typecheck, make contract-frontend, make test-frontend, make e2e

## Permanently Failed / Gave Up
- Stop reason: agent_run reported changed_files that do not match the actual git diff. reported=['api/app/main.py', 'api/app/rag/concept_mode.py', 'api/app/routers/ai_sage.py', 'api/tests/test_ai_sage_concept.py', 'web/src/__tests__/AISage.test.tsx', 'web/src/lib/api.ts', 'web/src/routes/AISage.tsx'] actual=['api/app/main.py', 'api/app/rag/concept_mode.py', 'api/app/routers/ai_sage.py', 'api/tests/test_ai_sage_concept.py', 'tasks/issue-131-decision-copilot-memos-and-calibration.md', 'web/src/__tests__/AISage.test.tsx', 'web/src/lib/api.ts', 'web/src/routes/AISage.tsx']
- Attempted mitigations:
- mitigation: No automated mitigation was recorded.
- Suggested human action: Fix the cited blocker and rerun the workflow on the same thread.
<!-- MACHINE_RENDERED_END -->

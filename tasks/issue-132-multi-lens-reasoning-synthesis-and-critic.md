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

## Scope
- Thesis-oriented query handling
- Extraction of thesis claims / assumptions from user input
- Key pushback questions
- Missing information detection
- Relevant author perspectives
- Live evidence from filings, transcripts, reports, and web research
- Synthesis and critique
- Updated thesis view in the output

## Out Of Scope
- Save/retrieve research memory
- Full memo workflow
- Outcome review / calibration
- Portfolio monitoring
- Autonomous recommendations

## Acceptance Criteria
- [ ] `AI Sage` can accept a thesis-style company prompt and classify it into company thesis mode.
- [ ] For a company thesis query, the system returns:
  - thesis / question
  - relevant authors
  - key pushback questions
  - missing information
  - fetched sources used
  - key facts extracted
  - author views
  - synthesis
  - critique
  - updated thesis view
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

## Suggested Implementation Shape
- Extend `POST /ai-sage/query` or add a closely related orchestration path.
- Add provider/tool integration for:
  - document fetching
  - web research
  - source extraction / normalization
- Response shape should remain sectioned and user-readable.

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- `curl -X POST http://localhost:8000/ai-sage/query -H "Content-Type: application/json" -d '{"query":"Here is my thesis on Tencent Music. Pressure test it."}'`
- Verify the answer includes:
  - pushback questions
  - live sources used
  - extracted facts
  - author perspectives
  - synthesis
  - critique

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

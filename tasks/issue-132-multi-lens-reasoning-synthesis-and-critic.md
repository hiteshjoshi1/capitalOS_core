# Issue 132: Multi-Lens Reasoning, Synthesis, And Critic

## Objective
- Build the first real reasoning layer on top of issue 130 retrieval and author wisdom.
- Let `AI Sage` reason on a problem using dynamically selected author lenses, then produce a synthesis and a critic pass that preserve disagreement instead of flattening it.
- Deliver the first implementation of the 4-layer architecture promised by Module 2:
  - shared knowledge layer
  - query-selected author-specific reasoning lenses
  - synthesis layer
  - critic layer

## Program Position
- Depends on issue 130.
- Supplies the reasoning substrate for issue 133 decision memos and issue 135 personal reflection.
- Should remain UI-testable through `Intelligence > AI Sage`.

## Architecture Decisions
- Author selection remains dynamic. No fixed “Buffett/Munger/Marks every time” behavior.
- Lens execution should be configuration-driven using author profile + reasoning lens metadata from the config/DB.
- Each lens output should be explicitly structured, not free-form prose only.
- The user should be able to see distinct per-author perspectives before they are collapsed into one blended answer.
- Synthesis must preserve:
  - common ground
  - meaningful disagreements
  - missing information
  - highest-risk assumptions
- Critic must challenge:
  - unsupported claims
  - citation mismatch
  - false consensus
  - weakly grounded conclusions
- Critic should validate both the per-author outputs and the combined synthesis, not just critique the final answer in isolation.
- This issue should not yet persist full decision memos. It should generate structured reasoning outputs that can later be saved by issue 133.

## Acceptance Criteria
- [ ] `AI Sage` query flow can select relevant authors for a question and run lens-specific reasoning for the selected authors.
- [ ] Lens outputs are visibly differentiated and grounded in retrieved evidence.
- [ ] Query responses include explicit per-author perspective sections before the combined synthesis.
- [ ] Add a synthesis stage that returns:
  - common ground
  - disagreements
  - decision-relevant variables
  - missing information
  - highest-risk assumptions
  - tentative conclusion
- [ ] Add a critic stage that returns:
  - strongest counterargument
  - least-grounded claim
  - citation support warnings
  - possible false consensus warning
- [ ] Query responses remain citation-backed and expose which citations informed which lens.
- [ ] `AI Sage` UI can display:
  - selected authors
  - lens outputs
  - synthesis
  - critic
- [ ] If the reasoning flow surfaces follow-up questions or open threads, they are shown to the user as optional next questions rather than automatically triggering external search.
- [ ] Add backend tests covering:
  - author selection
  - lens routing
  - synthesis shape
  - critic shape
  - citation propagation

## Suggested Implementation Shape
- Add services for:
  - author selection for reasoning
  - lens execution
  - synthesis
  - critic/red-team pass
- Add API endpoints or extend existing ones, likely near:
  - `POST /rag/reason`
  - `POST /rag/query`
  - `POST /rag/analyze/company-context`
- Use structured JSON outputs between stages rather than free-form chaining.

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- `curl -X POST http://localhost:8000/rag/reason -H "Content-Type: application/json" -d '{"query":"Would a capital-light software business with strong customer lock-in but deteriorating pricing power still count as high quality?"}'`
- Verify `AI Sage` renders:
  - selected authors
  - lens outputs
  - synthesis
  - critic

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

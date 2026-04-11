# Issue 133: Research Memory Mode

## Objective
- Deliver the third core mode:
  `Research Memory Mode`
- Let the user save useful outputs and retrieve them later by:
  - company
  - concept
  - checklist
  - thesis
  - topic
- Make repeated use compound knowledge instead of starting from zero every time.

## Program Position
- Depends on issues 130, 131, and 132.
- This is the third step in the ruthless build order:
  1. concept mode
  2. company thesis mode
  3. research memory

## Central Product Idea
- Good outputs should not disappear after one session.
- The system should make it easy to save and later retrieve:
  - prior research
  - stored notes
  - extracted evidence
  - past conclusions
  - key author references

## Scope
- Save research outputs from concept mode and company thesis mode
- Tag/index saved entries by:
  - company
  - concept
  - checklist
  - thesis
  - topic
- Retrieve saved research later by those keys
- Support simple note/research objects rather than heavy workflow machinery
- Keep the UI lightweight and directly useful

## Out Of Scope
- Full decision memo workflows
- Outcome review / calibration
- Feedback analytics
- Monitoring dashboards

## Acceptance Criteria
- [ ] The user can save a useful answer or research output from `AI Sage`.
- [ ] Saved research can be indexed under:
  - company
  - concept
  - checklist
  - thesis
  - topic
- [ ] The user can retrieve:
  - prior research
  - stored notes
  - extracted evidence
  - past conclusions
- [ ] `AI Sage` can answer prompts like:
  - "Show me everything I know so far about Tencent Music"
  - "Show me my notes on network effects"
- [ ] Saved research preserves links back to the evidence and sources used.
- [ ] Add backend tests for:
  - save research
  - retrieve research by company/topic/concept
  - evidence/source preservation
- [ ] Add frontend tests for save/retrieve interactions.

## Suggested Implementation Shape
- Add lightweight persisted objects close to:
  - `research_notes`
  - `research_note_evidence`
  - `research_topics`
- Keep storage simple and retrieval-first.
- Avoid over-designing memo/calibration schema here.

## Verification Plan
- `make api-rebuild`
- `make web-rebuild`
- `make test-backend`
- `make test-frontend`
- Save a concept-mode answer under a concept/topic
- Save a company thesis answer under a company
- `curl` retrieval examples:
  - `GET /research?company=TME`
  - `GET /research?topic=network-effects`
- Verify prior research can be found and reused

## Human Notes
- This issue should be judged by whether repeated use compounds knowledge.
- If the system stores outputs but they are hard to retrieve later, the issue is not successful.
- Keep this lightweight. The goal is reusable research, not workflow theater.

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

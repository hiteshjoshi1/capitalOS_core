# Issue 133: Guided Investment Intake And Decision Memos

## Objective
- Turn `AI Sage` from a reasoning surface into a guided investment intake assistant.
- Let the system ask clarifying questions from author lenses, collect missing information about a new investment, and produce a persisted decision memo.
- Start capturing the user’s own thinking in a reusable, reviewable format.

## Program Position
- Depends on issue 130 and issue 132.
- Feeds issue 135 by creating the decision artifacts that reflection/calibration needs.

## Architecture Decisions
- The system should not assume it already has enough context.
- If evidence or user-provided information is insufficient, it should ask follow-up questions rather than pretending certainty.
- Question generation should come from author lenses and missing-data analysis, not generic “tell me more” prompts.
- The memo is the first-class product object.
- Memo content should preserve:
  - question
  - evidence
  - lens reasoning
  - synthesis
  - critic output
  - user-supplied clarifications
  - confidence
  - assumptions
  - falsifiers
  - monitoring checklist

## Acceptance Criteria
- [ ] `AI Sage` can ask targeted follow-up questions when the query is under-specified.
- [ ] The system can generate a missing-information checklist for a new investment or business question.
- [ ] Add persisted decision memo object(s) and API surface to create, fetch, and list memos.
- [ ] Memo draft includes:
  - decision question
  - evidence summary
  - author lens views
  - synthesis
  - critic
  - recommendation / tentative conclusion
  - confidence
  - assumptions
  - falsifiers
  - monitoring checklist
- [ ] `AI Sage` UI supports:
  - showing clarification questions
  - submitting answers
  - showing memo draft
  - saving or updating memo
- [ ] Add tests for:
  - follow-up question generation
  - memo creation
  - memo retrieval
  - missing-data checklist generation

## Suggested Implementation Shape
- New persisted objects, names subject to judgment:
  - `decision_sessions`
  - `decision_memos`
  - optional `decision_memo_sections`
- Likely endpoints:
  - `POST /decision/start`
  - `POST /decision/{id}/answer-questions`
  - `GET /decision/{id}`
  - `GET /decision/recent`

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- `curl -X POST http://localhost:8000/decision/start -H "Content-Type: application/json" -d '{"question":"Should I study Company X further?"}'`
- `curl -X POST http://localhost:8000/decision/<id>/answer-questions -H "Content-Type: application/json" -d '{"answers":[...]}'`
- `curl http://localhost:8000/decision/<id>`
- Verify `AI Sage` can create and render a memo draft end to end

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

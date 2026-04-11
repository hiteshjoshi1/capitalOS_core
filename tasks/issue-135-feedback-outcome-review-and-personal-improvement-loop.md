# Issue 135: Feedback, Outcome Review, And Personal Improvement Loop

## Objective
- Close the loop between prior thinking and later reality.
- Help the user become a better investor and a better person by reviewing decisions, tracking mistakes, and surfacing recurring weaknesses in judgment.
- Turn CapitalOS from a smart research/reasoning tool into a compounding judgment system.

## Program Position
- Depends on issues 130, 132, and 133.
- Benefits materially from issue 134 but should still work with thinker + memo data alone.
- This is the issue where the “better investor and better person” goal becomes explicit product behavior.

## Architecture Decisions
- Outcome review is a first-class object, not an afterthought.
- Feedback and calibration should operate on stored memos and actual later reviews, not only instantaneous thumbs-up/down.
- This issue should only evaluate and summarize workflows that are already producing valuable research and memo outputs. It must not drive product complexity ahead of answer quality.
- Reflection should examine:
  - overconfidence
  - weak assumptions
  - repeated blind spots
  - poor domain fit
  - missed disconfirming evidence
  - recurring lens imbalance
- Keep the first version simple and useful:
  - review one memo
  - review recent memos
  - aggregate obvious patterns
- Avoid pretending to know realized investment truth automatically when it is not available; allow manual review inputs.

## Acceptance Criteria
- [ ] Add memo feedback capture beyond simple success/failure.
- [ ] Add persisted outcome review object linked to decision memos.
- [ ] Add calibration or reflection records that compare original confidence/thesis to later review.
- [ ] Add API and `AI Sage` views for:
  - recent decisions
  - outcome reviews
  - recurring mistakes / patterns
  - strongest calls / weakest calls
- [ ] System can answer prompts like:
  - “What patterns do you see in my bad calls?”
  - “Where do I tend to be overconfident?”
  - “Which assumptions break most often?”
- [ ] Add tests for:
  - feedback capture
  - outcome review linkage
  - calibration aggregation
  - reflection summary generation

## Suggested Implementation Shape
- New persisted objects, names subject to judgment:
  - `decision_memo_feedback`
  - `outcome_reviews`
  - `calibration_records`
  - optional `reflection_runs`
- Likely endpoints:
  - `POST /decision/{id}/feedback`
  - `POST /decision/{id}/outcome-review`
  - `GET /decision/recent`
  - `GET /decision/reflection-summary`

## Verification Plan
- `make api-rebuild`
- `make test-backend`
- Create memo via issue 133 flow
- `curl -X POST http://localhost:8000/decision/<id>/feedback -H "Content-Type: application/json" -d '{"tags":["missed_key_risk","overconfident"],"notes":"..."}'`
- `curl -X POST http://localhost:8000/decision/<id>/outcome-review -H "Content-Type: application/json" -d '{"what_happened":"...","assumptions_status":[...]}'`
- `curl http://localhost:8000/decision/reflection-summary`
- Verify `AI Sage` or related UI can show recent judgments and reflection outputs

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

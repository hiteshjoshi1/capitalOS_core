# Issue 113: Pipeline change
In the pipeline, there is a task-all. 
It runs plan, wait for human approval, runs build, runs review, if needs_fixes runs rework, and reviews again upto max retries. If review passes it runs ship and creates PR or updates existing PR

I want this stage to change, no human review gate in between
plan -> build -> review -> if needs_fxes -> rework (max_retries) -> if review passes -> create PR or update existing PR

- ensure that any other step does not break while making this change
- since you are running the same pipeline file which you are modifying make sure that changes in your code does not break the existing pipeline. Make sure that the changes are seprate until they are fully ready to be incorporated, no file corruption please

## Objective
- Describe the business/user objective in 1-3 bullets.

## Architecture Decisions
- Decision 1:
- Decision 2:

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement backend changes (if required)
- [ ] Implement frontend changes (if required)
- [ ] Add/update tests
- [ ] Run verification commands

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

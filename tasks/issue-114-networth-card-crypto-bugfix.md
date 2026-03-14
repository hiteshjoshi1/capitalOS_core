# Issue <id>: <title>

## Objective
In the dashboard, we have networth card. This has cash, stock, crypto and liabilities.

- The crypto total is wrong. S$ 183,620 is wrong
- The total I assume is close to what we see in crypto holdings. 

- why there are two different values one in net worth and one in crypto holdings , i assume 2 different APIs are being called which should not be the case.
- see if the db got corrupted due to experiments i did with coinbase ingestion earlier, if yes remove the corrupted data of coinbase
- Check the Crypto Holdings page as well and see if the current total of 122,378 is correct or not. It might also be impacted by earlier experiments wth coinbase
- there should be one value in net worth and crypto holdings



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

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

Issue 116: Cash Flow Category Mapping UI + Override Workflow
## Objective
# Issue 116: Category Mapping UI (User-Context Workflow)

- Build the category-mapping UI as an operational workflow under the User context, not on Dashboard.
- Dashboard must not show cash-flow mapping readiness/blocked cards or placeholders after this change.
- If mapping action is needed, signal it in User menu/navigation context only.

Core UX intent:
- Mapping is a maintenance action, not a dashboard insight.
- User should discover pending mapping work when opening the User section/menu.
- User can enter a dedicated mapping workspace and resolve items quickly.

Navigation requirements:
- Add a dedicated route: `/cash-flow/mapping`.
- Add entry under User menu “Navigate” section: `Cash Flow Mapping`.
- If unmapped items exist, show a clear pending indicator in User menu entry (badge/text).
- Do not add a top-level primary nav tab for mapping.
- Remove the current dashboard cash-flow placeholder card/message related to pending category mapping.

Mapping page requirements:
- Show unmapped transactions queue.
- Show current resolved category + source metadata where available.
- Support manual override action per transaction.
- Update row/queue state immediately after successful override.
- Include loading, empty, and error states.

Scope constraints:
- UI/frontend only in this story (consume existing backend APIs from issue-115).
- No backend schema/API changes.
- No unrelated UI redesign.

Human-verifiable checks:
- From User menu, I can see there is pending mapping work (when applicable).
- I can open `/cash-flow/mapping` from User menu.
- I can apply override and see queue update immediately.
- After refresh, overrides remain reflected.
- Dashboard no longer shows the old mapping-pending placeholder card.



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

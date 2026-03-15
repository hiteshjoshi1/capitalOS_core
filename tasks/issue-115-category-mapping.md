# Issue 115: Category Mapping

## Objective
# Issue: Cash Flow Category Mapping + Overrides

- Implement backend-only category mapping so cash flow is no longer blocked by missing final categorization logic.
- Keep this deterministic, auditable, idempotent, and safe for future ingestion files.
- Do not include UI changes in this story.

Backend-only human goals:
- Every cash-flow-relevant transaction can resolve to a final canonical category.
- Automatic mapping is rule-driven and deterministic.
- Manual override is supported at backend level and takes precedence over auto-mapping.
- Re-ingestion does not erase manual overrides.
- Unmapped transactions are explicitly discoverable via backend APIs.
- Category decision provenance is visible (rule-based vs manual).

Scope intent (backend only):
- Introduce canonical category taxonomy in backend.
- Add rule-based category mapping engine.
- Add persisted manual override capability and precedence logic.
- Add support to list unresolved/unmapped transactions.
- Add safe backfill path for existing transactions.
- Keep all existing API contracts backward compatible (additive changes only).

Backend-only human-verifiable checks:
- API can return unmapped transactions for a month/account set.
- API can apply a manual override to a transaction.
- After override, API returns the updated resolved category and source metadata.
- After re-ingesting the same source file, overridden transactions still return the same final category.
- API can show rule list and rule hit behavior.
- Existing spending/dashboard endpoints still return valid responses and do not regress.

Output requirement for implementation:
- At the end, provide exact `curl` commands (with sample IDs/placeholders) for:
  - listing unmapped transactions
  - creating/updating a mapping rule
  - applying a manual override
  - fetching transaction/category resolution state
  - proving override persistence after re-ingestion
- Include expected response snippets for each command so a human can verify quickly.

Safety constraints:
- No UI/frontend code changes in this issue.
- No fixture-specific hardcoding.
- No personal data committed.
- No unrelated file changes outside this issue scope.
- Keep diffs minimal and modular.



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

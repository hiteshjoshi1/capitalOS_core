# Issue 103: ui-ux-refresh

## Objective
- The current UX of the application sucks. It needs to look professional, like a personal finance dashboard that is actually made by proffesionals. The app should be minimalistic, clean and easy to navigate.
- It needs a UI placeholder for a logged in USER.The "User" as a functionality (Signup/ Login) is not implemented yet. User Sign Up login is out of scope of this feature.
- It needs a dark mode and light mode toggle that toggles between these modes.
- There are too many tabs - Dashboard, Ingest, Wallets, Crypto Holdings, Stock Holdings,Cash, Market data. The stock, cash and crypto exposure cards in dashboard should have links that expand to the Stocks Holdings, Cash Holdings, Crypto Holdings pages. These should not be tabs at the top.
- The settings like base currency should be inside User. The same goes for chosen month. 
- Market Data should not be there in UI for a regular user. For an Admin, may be yes. For now since we do not have user functionality implemented. Hide this section, i can access it directly via http://localhost:5173/market-data
- The tabs in the dashboard are hap hazard and does not create good UX. The information is good but needs to be better presented and visually scanable.
- Remove - "Local-first personal finance control plane. Numbers below are placeholders until ingestion is wired end-to-end."
- Expenses ingestion is not implemented yet , keep its cards as placeholder.
-  This PRD is about changing the Dashboard page and its UX only. We will change the other pages later in accordance with this design, while you can plan design and architecture wise for these pages, the implementation should be done in a seprate PRD
- If some information can be better presented, suggest
- This story should be UI first with minimal backend changes.
- Ensure code quality, tests updation, linting and a solid build when implementing.


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

### Retry Entry (2026-03-07T10:39:01Z)

```text
Pull latest main failed on attempt 1 with exit code 0: git pull --rebase
```

### Retry Entry (2026-03-07T10:39:02Z)

```text
Pull latest main failed on attempt 2 with exit code 0: git pull --rebase
```

### Retry Entry (2026-03-07T10:39:02Z)

```text
Pull latest main failed on attempt 3 with exit code 0: git pull --rebase
```

### Retry Entry (2026-03-07T10:39:02Z)

```text
Pull latest main failed after 3 attempts.
```

### Planning Output (claude-opus-4.6) (2026-03-07T10:46:58Z)

```text
● Now let me check specific details needed for the plan — the exact nav
  structure, the placeholder text, and existing test coverage.

● Now I have a complete picture. Let me write the plan.

● The task file is read-only (likely xattr-protected). I'll write the plan to
  the session folder and output it.

● Plan written to session plan.md. The task file at
  tasks/issue-103-ui-ux-refresh.md is read-only — you'll need to copy the
  acceptance criteria and architecture decisions into it manually, or unlock
  the file with xattr -d com.apple.quarantine tasks/issue-103-ui-ux-refresh.md
  first.

  Summary of the plan:

   - 7 architecture decisions: No new component library (extend CSS vars), data-theme toggle with
  localStorage, nav reduced to Dashboard + Ingest + User dropdown, reorganized grid hierarchy,
  App.tsx decomposed into ~8 card components, zero backend changes, user avatar placeholder with
  dropdown.
   - 5 risks: Test breakage (mitigated by updating tests), light theme contrast, component prop
  typing, responsive regression, wallet provider tree (no actual risk).
   - No blocking open questions.
   - 12 tasks in 4 phases: Foundation (theme + layout) → Dashboard decomposition → Styling polish
  → Tests & verification. All aligned to 13 acceptance criteria.
```

### Human Gate Reminder (2026-03-07T10:46:58Z)

```text
Review the plan and set '- [x] Approved for implementation' before build.
```

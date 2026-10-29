# Issue 42: GitHub Issues and Project board as the source of truth for work

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/42

## Objective
- One place shows what's next, in progress and waiting for review, instead of `tasks/*.md` files
  alone (the repo had 0 issues). Modelled on InvestOS's backlog board.

## Architecture Decisions
- **Board:** user Project #2 "CapitalOS backlog" (private), linked to the repo. Fields: Status (Next
  up, In progress, Fixed-To Review, Waiting on Hitesh, Backlog, Done), Priority (P0–P3), Size
  (S/M/L), Kind (Ops, Process, Feature, Bug, Security, Tech debt).
- **The GitHub issue number is the task id** (`tasks/issue-<n>-<slug>.md`,
  `feature/issue-<n>-<slug>`). *Rejected:* a separate id series, as InvestOS uses (B21, W14):
  the orchestration already parses `issue-<digits>-<slug>`, and one number is easier to follow.
  Legacy docs 201–214 keep their numbers; GitHub numbering would only reach them after ~150 more
  issues and PRs.
- `scripts/board.sh list|add|move` wraps `gh project` (option names match by prefix, so a bad
  status is an error listing the valid ones). It uses the id `item-add` returns, because
  `item-list` lags right after an add.
- Task docs carry an `Issue:` link: `tasks/_template.md` (filled in by `task_flow.sh`'s `<id>`
  substitution) and the orchestration's `DEFAULT_TEMPLATE`.

## Acceptance Criteria
- [x] AGENTS.md § Work Tracking: board, fields, ids, `Closes #n`, status flow. CLAUDE.md points to it.
- [x] Template and orchestration default template carry the issue link; `make orch-test` 201 passed.
- [x] Open follow-ups filed: #49 (Dependabot PR backlog, 23 PRs listed), #50 (Grafana 13 revisit).

## How To Test
- `scripts/board.sh list`, then `scripts/board.sh move 42 "Fixed-To Review"`.

<!-- IMMUTABLE_PLAN_END -->

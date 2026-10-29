# Issue 47: Session-start status: board, open PRs, stack health

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/47

## Objective
- Every session starts with the state of the work in view, as InvestOS's SessionStart hook
  shows its request queue.

## Architecture Decisions
- `scripts/status.sh` (`make status`) is read-only and always exits 0. It shows:
  - which stack this checkout drives (`make where`)
  - real-stack API health and containers up
  - deployed commit vs `origin/main` (from the last fetch, no network wait)
  - the newest verified backup's age (warns past 26h)
  - worktrees and the test instance
  - board items (In progress, Waiting on Hitesh, Fixed-To Review, Next up)
  - open PRs with CI state, with Dependabot's counted separately (#49)
- The two `gh` calls run in parallel: about 1.6s total. Without `gh`/network or Docker, each part
  prints one line ("unavailable", "Docker not running").
- `.claude/settings.json` gets a `SessionStart` hook running it; a failure prints a hint and
  never blocks the session. The existing `PreToolUse` guard is kept.
- Also fixed: `test-instance-drop` now deletes the pushed `test/<date>` branch once it's merged.
  `gh pr merge --delete-branch` couldn't while the worktree still had it checked out, which left
  merged test branches on the remote.

## Acceptance Criteria
- [x] `make status` runs in ~1.6s and changes nothing.
- [x] No `gh` → board and PRs say "unavailable"; no Docker → "Docker not running"; exit 0 in both.
- [x] Hook added alongside the existing PreToolUse hook (JSON valid).

## How To Test
- `make status`; start a new Claude Code session and see it printed.

<!-- IMMUTABLE_PLAN_END -->

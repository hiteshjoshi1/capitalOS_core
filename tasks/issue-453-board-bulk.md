# Issue 453: board.sh: bulk moves in one GraphQL call, cached IDs, back-off on rate limits (R6 from #431)

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/453

## Objective
- Board updates stop failing on GitHub's secondary rate limit (10–11 Nov: #353, #354, #359 went missing).

## Architecture Decisions
- Logic moves to `scripts/board.py` (stdlib only, run with `python3 -I`); `board.sh` stays the entry point.
- Project and field/option IDs cached in `~/.cache/capitalos/board-ids.json` (7 days; refetched once if a
  change fails with the cached IDs).
- Items looked up per issue with one aliased GraphQL query (`issue.projectItems`), not a 500-item list.
- `move`/`add` take any number of issues; all changes are one aliased mutation.
- `gh` retried with exponential back-off (5s, 10s, 20s, 40s) on rate-limit answers.

## Acceptance Criteria
- [x] `board.sh move 359 361 362 "Fixed-To Review"` = one lookup + one mutation (+ IDs on a cold cache).
- [x] A bad status or an issue not on the board changes nothing.
- [x] Rate-limit answers are retried; a limit that doesn't clear fails with GitHub's message.
- [x] `list` unchanged.

## How To Test
- `scripts/test-board.sh` (fake gh; run by `make lint`).
- Real board: `scripts/board.sh add 449 450 451 452 453 "In progress"` (3.6s) and `move 451 453 "In progress"` (2s).

<!-- IMMUTABLE_PLAN_END -->

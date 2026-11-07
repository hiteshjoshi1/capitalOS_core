# Issue 269: make worktree-prune

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/269

## Objective
- One command frees every merged worktree and its Docker stack (containers, volumes, networks,
  images), so Docker stops running out of network addresses.

## Architecture Decisions
- `scripts/worktree-prune.sh`, `make worktree-prune` (dry run) / `APPLY=1` (removes), like `docker-prune`.
- Merged = the branch tip is an ancestor of origin/main **and not on main's first-parent line**: a fresh
  branch with no commits sits on that line and is kept (caught in the dry run: the four sprint agents'
  new worktrees would otherwise have counted as merged).
- Also kept: unmerged, dirty (tracked changes or untracked files), running stack, main checkout, test
  instance; protected projects capitalos / capitalos-oss-test / capitalos-test are never dropped.
- Docker resources found by compose labels: the Makefile's ISO_NAME for the directory plus projects
  whose containers ran from it (`com.docker.compose.project.working_dir`), so it works for worktrees
  whose Makefile predates `instance-drop`.

## Acceptance Criteria
- [x] Dry run lists each merged worktree with its containers/volumes/networks; keeps the rest with a reason.
- [x] APPLY=1 removes the Docker resources, the worktree and the merged branch.
- [x] `scripts/test-worktree-prune.sh` (14 checks, stub docker, throwaway repo), run by `make lint`.

## How To Test
- `scripts/test-worktree-prune.sh`
- `make worktree-prune` in the main checkout (dry run).

<!-- IMMUTABLE_PLAN_END -->

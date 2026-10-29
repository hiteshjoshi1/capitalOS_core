# Issue 45: Batch test branch and a separate test instance before main

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/45

## Objective
- Hitesh tests a batch of PRs on a separate app with a copy of his real data **before** anything
  reaches `main`, then one tested PR lands the batch. Adapted from InvestOS's A43 / D-232.

## Architecture Decisions
- `scripts/test-instance.sh` (via `make test-instance*`, main checkout only):
  - **up** merges `main` + the PRs in order (`--no-ff`, from `pull/<n>/head`) into `test/<date>`
    in the worktree `../capitalOS-worktrees/test-instance`. A conflict stops and is named, and is
    resolved by a person; **start** continues.
  - It runs `make verify` (lint incl. pin and guard checks, typecheck, backend + frontend tests).
    A failure stops it, and nothing is served.
  - It restores the newest **verified** backup (#41) into the instance's own Postgres and checks
    its row counts against the backup's `.counts`, applies the batch's migrations to that copy
    (so migrations are tested on real data), and serves the API and the Vite app.
  - **pr** pushes the branch and opens one PR to `main` that `Closes` every issue the batch's PRs
    close (`closingIssuesReferences`). **drop** stops it and removes containers, volumes,
    worktree, local branch and images.
- **Isolation** is #44's: compose project `capitalos-test`, `docker-compose.isolated.yml`. Fixed
  ports so Hitesh can bookmark it: web 5174, API 8021, Postgres 5434. The isolated `api` now sets
  every **scheduler off**, so a dev or test copy never calls IBKR / Coinbase / market data on its own.
- **Banner:** `InstanceBanner` (outside the router, so it shows on login too) renders
  `VITE_INSTANCE_LABEL` and prefixes the tab title: red TEST for the test instance, amber DEV
  for any worktree's `make web-up`. The real app sets no label and shows nothing.
- *Simpler than InvestOS:* no model-call registry or promotion, because CapitalOS makes no paid
  model calls during a rebuild.
- *Rejected:* a long-lived `develop` branch. It would drift from `main` and resolve conflicts twice.

## Acceptance Criteria
- [x] Batch `#54 + #19`: both merged, then **`make verify` caught #19** (Dependabot's
      `eslint-plugin-react-hooks` bump: 7 new lint errors). Nothing was served; noted on #19 for #49.
- [x] Batch `#54`: verify passed (guard 13, backend 439, frontend 271); verified backup restored
      with identical counts (57 tables); migrations applied; served on :5174 / :8021 with the TEST
      banner on login and after it; 597 transactions (same as real); schedulers disabled; real
      containers unchanged.
- [x] `drop` removes everything; the test stack can't touch the real DB (#44 isolation).
- [x] Documented in AGENTS.md § Process Rules and CLAUDE.md.

## How To Test
- `make test-instance PRS="<n>"`, open http://localhost:5174, then `make test-instance-drop`.

<!-- IMMUTABLE_PLAN_END -->

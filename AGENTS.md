# AGENTS.md
Project: CapitalOS
Purpose: Local-first AI-native personal finance + investing system
Architecture: Postgres + FastAPI + React (Vite) in Docker
Mode: Deterministic, verifiable, reproducible

For Claude Code, `CLAUDE.md` is the canonical operational quickstart (run/verify
commands, ports, gotchas); this file holds the durable principles and contract rules.

---

# Core Principles

1. No silent breaking changes.
2. All changes must compile and run.
3. All APIs must remain OpenAPI-compatible.
4. No hardcoded IDs.
5. All logic must be testable via curl.
6. Every change must be verifiable via a Makefile command.
7. Code external/model/vendor integrations to a narrow interface with provider selection via config; keep provider-specific logic isolated so providers can be swapped or disabled without changing callers.
8. Never modify main branch
9. Never delete unrelated files
10. Do not refactor outside scope
11. If acceptance criteria unclear, update plan doc and stop
12. Max 3 retries per failing command
13. Test every change
14. Run unit tests and integration tests as per changes made

---

# Work Tracking (GitHub Issues + board)

The backlog is the GitHub Project **[CapitalOS backlog](https://github.com/users/hiteshjoshi1/projects/2)**
(issue #42): one GitHub issue per unit of work in `hiteshjoshi1/capitalOS_core`. Never keep a
second backlog, TODO list or roadmap file.

| Field | Values |
| --- | --- |
| **Status** | Next up, In progress, Fixed-To Review, Waiting on Hitesh, Backlog, Done |
| **Priority** | P0 Data loss or wrong data, P1 High, P2 Medium, P3 Low |
| **Size** | S (under a day), M (a few days), L (a week or more) |
| **Kind** | Ops, Process, Feature, Bug, Security, Tech debt |

- **Work with no issue gets an issue first**, with all four fields set:
  `gh issue create ...` then `scripts/board.sh add <n> "Next up" P2 S Ops`.
- **The issue number is the task id.** Spec and journal: `tasks/issue-<n>-<slug>.md` (from
  `tasks/_template.md`, with its `Issue:` link). Branch: `feature/issue-<n>-<slug>`. The
  orchestration (`make task-*`) parses this name. Docs `issue-201` to `issue-214` predate the board
  and use their own legacy numbers.
- **Work in a worktree, never on a branch in the main checkout** (#44). The real-data API
  bind-mounts the main checkout's `./api/app` with `--reload`, so a branch checked out there runs
  against the real data. Use `make worktree ISSUE=<n> SLUG=<slug>`; the main checkout stays on
  `main`. A worktree gets its own isolated stack (`make where` shows its project and ports;
  `make up`, `make web-up`, `make db-migrate` there touch only it; `make instance-drop` removes
  it). In the main checkout, stack-changing targets refuse on any branch but `main`.
- **The PR description says `Closes #<n>`**, so the merge closes the issue.
- **Status moves with the work** (`scripts/board.sh move <n> "<Status>"`):

  | Status | When |
  | --- | --- |
  | Next up | Ready to be worked, in board order |
  | In progress | On starting: the branch is cut |
  | Fixed-To Review | On finishing: tests pass, the PR is open, and an issue comment says what changed, how it was checked, and what to look at |
  | Waiting on Hitesh | Only Hitesh can decide or do the next step |
  | Done | **Only Hitesh** moves an item here. A merged item stays in Fixed-To Review until he does. |

- See the process rules below for sprints and merging.

---

# Process Rules (issue #43)

These are Hitesh's standing instructions. **A new standing rule goes into this file in the same
change that first applies it**: a rule kept only in one tool's private memory binds no other
implementer. Precedence: Hitesh's word in the moment, then this file, then the rest of the docs.

- **Sprints.** Propose a sprint as a list of board issues, each explained in one plain line, and
  **wait for Hitesh's okay before working any of them**. An issue filed during a sprint waits for
  the next sprint unless he okays it. (The 2026-10-29 sprint, #41–#47, was okayed: "implement
  all of the things that you listed ... start on each one by one".)
- **Merging.** A PR is merged only when Hitesh says so, and the word covers only the PRs it
  names (or the sprint it okays). Never merge on your own judgement. Never commit to `main`.
- **Status.** Follow the board flow in § Work Tracking. A merged item stays in Fixed-To Review;
  only Hitesh moves it to Done. Feedback on review sends it back to In progress on the same
  branch.
- **Decisions.** A choice with real alternatives gets an entry in
  [docs/decisions.md](docs/decisions.md) (D-n): what was chosen, what was rejected and why, and
  the issue or PR. Link the D-n from the PR.
- **Self-review before "done".** Re-read the change against the original ask and your own plan,
  not only against the tests you wrote:
  - Was the thing asked for built, or a narrower, safer-looking substitute?
  - Every acceptance criterion in the issue, not only the ones the plan scoped in.
  - **Siblings and side effects.** What else uses the thing you changed? (#38: hardening Postgres's
    `/tmp` in #33 broke `db-backup`, which went through it.)
  - **Never mask a failure.** No `cmd | tail` or `cmd | grep` where the exit status matters
    (zsh: `${pipestatus}`; bash: `set -o pipefail`). A step that must succeed before the next is
    checked, not assumed. (#38: a failing backup was piped into `tail`, and the restart went
    ahead without it.)
  - A claim without a test is a gap: "checked by hand" says so.
- **Report faithfully.** A failed test, a skipped step, or a check done by hand rather than by a
  test is said so, with the output.
- **Check before asserting absence.** "Do we have X?" is a search of code, schema and docs, not
  a recollection.
- **Talking to Hitesh.** Explain every id and term in a plain line ("#45 (test a batch of PRs on
  a separate instance)", never just "#45"). For a decision: what it is, what each answer
  changes, and a recommendation.
- **Supply chain.**
  - Pin every image and Action by digest or SHA (`scripts/check-pinned-refs.sh`).
  - Adopt a release only once it's at least two weeks old, unless it fixes an exploited issue.
  - A new direct dependency is named to Hitesh, with what it does, who maintains it and when it
    was last released, before it's added.


---

# Environment Assumptions

- Docker installed
- Docker Compose available
- Node 22
- Python 3.12 (only inside container)
- Postgres 16 (Docker)
- timeout 60m codex exec ...

---

# Single Source of Truth

Backend:
- api/app/

Frontend:
- web/src/

Database:
- Postgres in Docker

---

# One-Command Lifecycle

## Start everything

make up

## Stop everything

make down

## Rebuild API

make api-rebuild

## Rebuild Web

make web-rebuild

## Reset database (DESTRUCTIVE)

make db-reset

## Run API tests (curl smoke)

make api-smoke

## Quick verify (default)
make up
make api-smoke
make web-up  


---

# Verification Rules

After ANY backend change:

1. make api-rebuild
2. curl $(make api-url)/health
3. curl $(make api-url)/dashboard/summary?month=YYYY-MM

(`make api-url` prints the API base for this checkout: `http://127.0.0.1:8011` when the
local `docker-compose.oss-test.yml` override is present, otherwise `http://127.0.0.1:8000`.)

After ANY frontend change:

1. make web-rebuild
2. open http://localhost:5173

---

# Snapshot Rule

- Snapshot anchor day controlled via:
  SNAPSHOT_DAY env var
- Default: 1
- Effective snapshot = max(as_of) <= anchor

Never change this logic silently.

---

# API Contract Rules

Never remove fields from responses.

You may:
- Add optional fields
- Add new endpoints

If modifying response schema:
- Update OpenAPI
- Update TypeScript types
- Update frontend rendering

---

# Coding Standards

Backend:
- SQLAlchemy ORM for models
- Raw SQL allowed only for aggregation
- No business logic in routers
- Pure functions for calculations

Frontend:
- TypeScript strict
- No any
- API types must mirror backend response
- No hardcoded month

---

# Data Rules

Transactions:
- Signed amounts
- Transfers must not affect income/expense
- Fees must reduce net

Positions:
- One snapshot per month
- Snapshot_day configurable

---

# Adding a New Feature

Steps:

1. Update DB (DDL or migration)
2. Update models
3. Update router
4. Update API types
5. Update frontend
6. make api-rebuild
7. make web-rebuild
8. Run api-smoke

No partial implementations.

---

# Future Modules (Do Not Implement Yet)

- CSV ingestion engine
- Realized P&L engine
- Valuation service
- Portfolio attribution engine

These belong to later modules.

---

# OpenAPI

Spec available at (API base from `make api-url`; 8000 on a fresh clone, 8011 with the local OSS override):
http://localhost:8000/openapi.json

Interactive docs:
http://localhost:8000/docs

Never break these routes.

---

# Definition of Done

A change is complete only if:

- Containers start
- No import errors
- No SQL errors
- Dashboard loads
- API returns valid JSON
- Types compile

---

# Philosophy

This system is:

- Deterministic
- Auditable
- Reproducible
- Infrastructure-first
- AI-native but not AI-dependent

---

## Change budget
- Prefer minimal diffs.
- Do not reformat unrelated files.
- No repo-wide refactors unless explicitly asked.
- Touch at most N files unless task requires more.

We build instrumentation first.
Intelligence comes later.

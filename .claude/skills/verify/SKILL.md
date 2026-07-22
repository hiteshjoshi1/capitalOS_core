---
name: verify
description: Verify a code change in CapitalOS actually works — which make/docker/npx command to run per change type, and the known-failing tests that are not regressions. Use before considering any change in this repo done.
---

# Verifying CapitalOS changes

Match the command to what actually changed — don't run the whole suite for a one-file frontend edit.

## Backend (`api/app/`)
```bash
make api-rebuild                      # rebuild image + restart container — required, code isn't hot-reloaded
docker compose run --rm api pytest    # full backend suite (runs INSIDE Docker, not on the host)
docker compose run --rm api pytest tests/test_X.py       # one file
docker compose run --rm api pytest tests/test_X.py -k name  # one test
```
`make test-backend` is equivalent to the full-suite form above.

**Fast inner loop (local venv, skips the Docker rebuild)**: this repo has a
host-side `.venv` at the repo root with the same deps installed. For quick
iteration on a single test file while writing code, it's faster to run
straight against it instead of rebuilding the api image every time:
```bash
cd api && ../.venv/bin/python -m pytest tests/test_X.py -k name -q
```
This is genuinely faster but **not a substitute** for the Docker-based run —
the api image is the actual deployed environment (its installed deps can
differ, e.g. the known `html5lib`/`openpyxl` gap below only shows up there).
Use the local venv while iterating, then confirm with `make api-rebuild` +
`make test-backend` before calling a backend change done.

**Known-failing, not a regression**: 13 tests under `test_uob_*` / `test_ingest_uob_*` fail in this environment because `html5lib`/`openpyxl` aren't installed in the api image. If you see exactly these fail and nothing else, your change is clean.

**Silent gap**: `make lint` / `make typecheck` do **not** actually check the backend today — `ruff`/`mypy` aren't installed in the api image, so those steps silently no-op for Python. Don't rely on them to catch backend issues; read the diff carefully instead (this is tracked as backlog work, not yet fixed).

## Frontend (`web/src/`)
```bash
cd web && npx vitest run <file>       # fast, one file — prefer this for the inner loop
cd web && npx vitest run              # full suite
cd web && npx tsc -b --pretty false   # typecheck (this one DOES work, unlike the backend)
cd web && npx eslint .
```

## Migrations (`migrations/NNN_*.sql`)
Add the numbered file, then:
```bash
make db-migrate
```
Tracked in the `schema_migrations` table — safe to re-run, already-applied files are skipped automatically. Never edit an already-applied migration; add a new one instead. Any destructive migration content (`DROP TABLE`/`TRUNCATE`/`DELETE FROM` without `WHERE`) will be blocked by the repo's `PreToolUse` hook if run directly via `psql -c` — that's expected; put destructive intent in a reviewed migration file, not an ad hoc command.

## RAG / research corpus
```bash
make rag-eval                 # eval harness against golden queries
make rag-eval-compare CONFIG_A=... CONFIG_B=...
make rag-eval-drift OLD_REPORT=... NEW_REPORT=...
```
Golden queries live in `api/app/rag/eval/fixtures/rag_golden_queries.yaml`.

## Full gate (rarely needed for a single change)
```bash
make verify   # lint + typecheck + backend/frontend tests — remember the lint/typecheck backend gap above
make test-all # also runs e2e + orchestration tests — slow, use sparingly
```

## Manual/UI verification
See the `run` skill for driving the actual app (curl for API, Playwright for UI) — type-checking and unit tests confirm correctness, not that a feature genuinely works end to end.

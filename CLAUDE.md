# CLAUDE.md

Operational quickstart for Claude Code in this repo. For principles, API-contract
rules, and coding standards, see `AGENTS.md`. For product vision, see `ReadMe.md`
and the `PRD-*.md` docs.

## Stack
Postgres 16 (pgvector) + FastAPI + React (Vite/TS), all in Docker via `docker-compose.yml`.

## Run
- `make up` — starts everything (postgres + api).
- Web: `cd web && npm run dev` → `http://localhost:5173`.
- API: `http://localhost:8000` (health: `curl http://localhost:8000/health`).
- Demo login: `demo` / `Test@1234`.
- `make down` / `make api-rebuild` / `make web-rebuild` / `make db-reset` (destructive).

## Verify (match to what changed)
- Backend code: `make api-rebuild` then `make test-backend` (runs **inside Docker**:
  `docker compose run --rm api pytest`). For one file: `docker compose run --rm api pytest tests/test_X.py`.
- Frontend code: `cd web && npx vitest run <file>` (fast) or `npm test -- --run` (full).
- New/changed migration: add `migrations/NNN_*.sql`, then `make db-migrate`
  (tracked in `schema_migrations`; safe to re-run, already-applied files are skipped).
- `make verify` runs frontend and backend lint + typecheck + backend/frontend tests.
- `/verify` and `/run` skills exist under `.claude/skills/` — prefer them over rediscovering this by hand.

## Known gaps (not regressions if you hit these)
- Postgres logs a "collation version mismatch" warning on every query — benign, ignore.
- The backend ruff/mypy baseline is intentionally permissive while the pre-existing
  warning backlog is addressed incrementally; both tools run and fail on configured checks.

## Conventions
- One `tasks/issue-NNN-<slug>.md` doc per unit of work (see `tasks/_template.md`).
- One feature branch + one PR per issue. **Never commit directly to `main`.**
- Numbered, sequential `migrations/NNN_*.sql` — never edit an already-applied migration.
- Never remove a field from an API response; only add. Keep TS types mirroring backend
  response shapes (see `AGENTS.md` § API Contract Rules).

## RAG / research corpus
- `config/rag_authors.yaml` is the source of truth for authors (id, domains, weight,
  `photo_url`, etc.). It's **bind-mounted read-only** into the api container
  (`./config:/app/config:ro`), so edits are live immediately — no rebuild needed.
  Apply DB-side sync with `POST /rag/authors/sync-config` if you added/changed an author.
- Eval harness: `make rag-eval`, `make rag-eval-compare`, `make rag-eval-drift`,
  `make rag-eval-pdf-gate`. Golden queries: `api/app/rag/eval/fixtures/rag_golden_queries.yaml`.

## Headless browser QA (screenshots)
Playwright works, but the dev server (5173) and API (8000) are different origins and the
api container doesn't set permissive CORS for arbitrary tooling — launch Chromium with
`--disable-web-security --disable-site-isolation-trials` for local screenshot/QA scripts
only (never ship this flag anywhere real).

## Config facts
- `SNAPSHOT_DAY=1` (env var, see `.env`) — controls the monthly snapshot anchor day.
- Node 22, Python 3.12 (inside container only).

## Remote dev (phone/away from the home machine)
See `docs/workflows/remote-dev.md` — `claude.ai/code` (web) for non-DB-dependent
work, or Tailscale+SSH+tmux into the home machine for anything needing the live
Postgres/containers.

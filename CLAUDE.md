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
- `make verify` runs lint + typecheck + backend/frontend tests, but note the gap below.
- `/verify` and `/run` skills exist under `.claude/skills/` — prefer them over rediscovering this by hand.

## Known gaps (not regressions if you hit these)
- `make lint` / `make typecheck` **silently skip the backend** — `ruff`/`mypy` aren't
  installed in the api image, so only the frontend is actually checked today.
- 13 tests under `test_uob_*` / `test_ingest_uob_*` fail in this environment (missing
  `html5lib`/`openpyxl` in the api image) — pre-existing, unrelated to your change.
- Postgres logs a "collation version mismatch" warning on every query — benign, ignore.
- `.github/workflows/pr-validate.yml` is `workflow_dispatch` only — CI does not run
  automatically on PRs yet.

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

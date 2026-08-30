---
name: run
description: Launch and drive the CapitalOS app (Postgres + FastAPI api in Docker, React/Vite web) for this project. Use whenever asked to run, start, screenshot, or confirm a change works in the real app.
---

# Running CapitalOS

## Launch

```bash
make up          # starts postgres + api containers (docker compose)
cd web && npm run dev   # starts the Vite dev server (foreground; use run_in_background or nohup if you need it detached)
```

- API: `http://localhost:8000` — health check: `curl http://localhost:8000/health`
- Web: `http://localhost:5173` (Vite will pick 5174+ if 5173 is already taken by another running session — check before assuming which port is live)
- Demo login: username `demo`, password `Test@1234`

If containers are already running (common — check first with `docker compose ps` before starting anything new):
```bash
docker compose ps
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health
```

## After a backend code change
`make api-rebuild` (rebuilds the image + restarts the container) before the change is live. Config-only changes under `config/` do **not** need a rebuild — `./config` is bind-mounted read-only into the api container (see `docker-compose.yml`), so edits are live immediately.

## Driving it (don't just launch)

- **API**: hit an actual endpoint with `curl`, read the JSON body. For authenticated routes, log in first:
  ```bash
  TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' \
    -d '{"username":"demo","password":"Test@1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
  curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/dashboard/summary?month=YYYY-MM
  ```
- **Web UI / screenshots**: use Playwright (already a dependency in `web/`, browsers pre-installed). Two gotchas specific to this repo:
  1. The dev server (5173/5174) and API (8000) are different origins and the api container's CORS is not permissive for arbitrary tooling ports — launch Chromium with `--disable-web-security --disable-site-isolation-trials` for local screenshot/QA scripts only. Never ship or suggest this flag for anything real.
  2. Log in via the `/login` form first (`demo` / `Test@1234`) before navigating to any authenticated route — most of the app is behind `RequireAuth`.
  3. A minimal script must run from inside `web/` (or `node` won't resolve the local `playwright` package) — e.g. copy a temp `.mjs` script into `web/`, run `node script.mjs`, then delete it.

## Known gotchas
- Postgres logs a "collation version mismatch" warning on every query via `docker compose exec` — benign, ignore it.
- If a `docker compose exec -T api psql`/python one-liner is needed for a read-only check (e.g. inspecting account ownership), that's normal and fine; anything that mutates data belongs in a proper `migrations/NNN_*.sql` file instead (see the `verify` skill / `CLAUDE.md`).

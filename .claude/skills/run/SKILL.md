---
name: run
description: Launch and drive the CapitalOS app (Postgres + FastAPI api in Docker, React/Vite web) for this project. Use whenever asked to run, start, screenshot, or confirm a change works in the real app.
---

# Running CapitalOS

## Launch

```bash
make up          # starts postgres + api containers (docker compose, project chosen by the Makefile)
cd web && npm run dev   # starts the Vite dev server (foreground; use run_in_background or nohup if you need it detached)
```

- API: `make api-url` prints its base URL — `http://127.0.0.1:8001` in a checkout with the local `docker-compose.oss-test.yml` override (the real-data OSS stack), `http://127.0.0.1:8000` on a fresh clone. Health check: `curl $(make api-url)/health`. It is published on loopback only.
- Web: `http://localhost:5173` (Vite will pick 5174+ if 5173 is already taken by another running session — check before assuming which port is live)
- Demo login: username `demo`, password `Test@1234`
- With `web/.env.local` setting `VITE_API_BASE=/api` the browser only talks to the Vite server, which proxies `/api/*` to the API. Call it directly with `$(make api-url)/…` from curl, or through the proxy as `http://localhost:5173/api/…`.

If containers are already running (common — check first with `make ps` before starting anything new; never start the retired default-project stack by hand):
```bash
make ps
curl -s -o /dev/null -w "%{http_code}\n" $(make api-url)/health
```

## After a backend code change
`make api-rebuild` (rebuilds the image + restarts the container) before the change is live. Config-only changes under `config/` do **not** need a rebuild — `./config` is bind-mounted read-only into the api container (see `docker-compose.yml`), so edits are live immediately.

## Driving it (don't just launch)

- **API**: hit an actual endpoint with `curl`, read the JSON body. For authenticated routes, log in first:
  ```bash
  API=$(make api-url)
  TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
    -d '{"username":"demo","password":"Test@1234"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
  curl -s -H "Authorization: Bearer $TOKEN" "$API/dashboard/summary?month=YYYY-MM"
  ```
- **Web UI / screenshots**: use Playwright (already a dependency in `web/`, browsers pre-installed). Two gotchas specific to this repo:
  1. If the web app calls the API directly (no `VITE_API_BASE=/api`), the dev server (5173/5174) and API are different origins and the api container's CORS is not permissive for arbitrary tooling ports — launch Chromium with `--disable-web-security --disable-site-isolation-trials` for local screenshot/QA scripts only. Never ship or suggest this flag for anything real. With the `/api` proxy setup everything is same-origin and the flag isn't needed.
  2. Log in via the `/login` form first (`demo` / `Test@1234`) before navigating to any authenticated route — most of the app is behind `RequireAuth`.
  3. A minimal script must run from inside `web/` (or `node` won't resolve the local `playwright` package) — e.g. copy a temp `.mjs` script into `web/`, run `node script.mjs`, then delete it.

## Known gotchas
- Postgres logs a "collation version mismatch" warning on every query (e.g. via `make db-query`) — benign, ignore it.
- If a read-only `make db-query QUERY='SELECT …;'` (or `make api-shell`-style one-liner) is needed for a read-only check (e.g. inspecting account ownership), that's normal and fine; anything that mutates data belongs in a proper `migrations/NNN_*.sql` file instead (see the `verify` skill / `CLAUDE.md`).

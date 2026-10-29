# Issue 206: Software supply chain audit (frontend + backend dependencies)

## Objective
- Scan every frontend (npm) and backend (Python) dependency, including transitive ones, for known advisories.
- Fix all critical/high issues and anything with a non-breaking fix; document what remains and why.

## Architecture Decisions
- Backend audited **inside** `python:3.12-slim` (the API image base) with `pip-audit`, so the resolved
  transitive tree matches what ships. The API image was also scanned with Trivy (OS packages + Python).
- `@app.on_event("startup")` moved to a `lifespan` handler: Starlette 1.x (required to clear its
  advisories) removed `on_event`. Schedulers start exactly as before; `TestClient(app)` (no `with`)
  still does not run startup, so tests are unaffected.
- `yfinance` 1.2.0 → 1.7.0: 1.2.0 caps `curl_cffi` below the fixed release.
- `react-router-dom` 6 → 7: no 6.x release fixes the open-redirect advisories. The app only uses the
  declarative API (`BrowserRouter`, `Routes`, `Link`, `Navigate`, hooks), which is unchanged in v7.
- `vitest`/`@vitest/coverage-v8` 2 → 5: clears the critical tinypool RCE and vitest UI file-read
  advisories (dev-only). No config changes were needed.
- npm `overrides`:
  - `jayson` → ^5.0.0 (pulled by `@solana/web3.js`, which still asks for ^4). The only part web3.js
    bundles is `jayson/lib/client/browser`, which is API-identical in v5; v5 drops the vulnerable
    `uuid@8` / `stream-json@1` dependencies entirely.
  - `image-size` → ^2.0.4 (pulled via react-native `metro` from the Solana mobile adapter; never
    executed in this web app).
- Dockerfile upgrades pip before installing requirements (pip 25.0.1 in the base had advisories).

## Acceptance Criteria
- [x] `npm audit` reports 0 vulnerabilities.
- [x] `pip-audit` inside the API image reports no known vulnerabilities.
- [x] Trivy: no fixable HIGH/CRITICAL OS packages in the API image when built on a current base.
- [x] Backend tests, ruff, mypy pass; frontend tsc, eslint, vitest, and `vite build` pass.

## How To Test
- `make api-rebuild && make test-backend` (rebuild with `docker pull python:3.12-slim` first so the
  OS layer is current).
- `cd web && npm ci && npm audit && npx tsc -b && npx eslint . && npx vitest run && npx vite build`.
- `docker compose run --rm --no-deps api sh -c 'pip install -q pip-audit && pip-audit'`.

<!-- IMMUTABLE_PLAN_END -->

## Scan results

### Before
- npm: 34 (4 critical, 16 high, 13 moderate, 1 low). Notable: tinypool RCE / vitest UI file read
  (dev), vite dev-server file read + `fs.deny` bypass (relevant: Vite listens on Tailscale),
  react-router open redirect, rollup path traversal, shell-quote, lodash, postcss, ws, form-data.
- Python: 48 advisories in 10 packages: starlette (via fastapi), python-multipart, PyJWT,
  cryptography, lxml, pynacl, python-dotenv, curl_cffi (via yfinance), pytest, pip.
- API image (Trivy, local base built Mar 2026): 75 fixable HIGH/CRITICAL Debian packages.

### After
- npm: 0. Python (`pip-audit`): 0. API image OS packages: 0 fixable HIGH/CRITICAL on Debian 13.7.

### Residual (not fixed here)
- Trivy flags `msgpack 1.1.2`, `urllib3 2.7.0`, `setuptools 70.3.0` — these are **pip's own vendored
  copies** in the latest pip (26.2.2). Not importable by the app; only used by pip at build time.
  The app's own urllib3 resolves to 2.8.0 (clean). Revisit when pip ships updated vendors.
- Third-party compose images (fixable HIGH/CRITICAL, Trivy): local `postgres:16` 117/19 — the
  local tag is a stale Mar 2026 pull; current upstream `postgres:16` is 25/2, so a `docker pull`
  + container recreate fixes most of it. `grafana/grafana:11.2.2` 141/13, `grafana/loki:3.2.1` 59/3,
  `grafana/alloy:v1.4.3` 74/4 are pinned old releases; bumping them needs observability config
  testing, so it is a follow-up. All of these are bound to 127.0.0.1.

## Deterministic Gate Results
- `lint`: pass — ruff (backend), eslint (frontend)
- `typecheck`: pass — mypy 95 files, `tsc -b`
- `tests`: pass — backend full pytest suite in the rebuilt image; frontend 40 files / 268 tests
- `e2e`: skip — stack not running; headless smoke of the built app: `/login` renders, no console errors
- `api-smoke`: pass — container boots, lifespan starts all three schedulers, `/health` → 200

## Human Action Summary
- Behaviour-relevant bumps to watch after deploy: `yfinance` 1.7 (live quote fetches are mocked
  in tests) and `PyJWT` 2.15 (auth tests pass).
- `docker pull postgres:16` and recreate the postgres container at a convenient time.
- Follow-up: bump Grafana/Loki/Alloy pins and run `make observability-smoke`.

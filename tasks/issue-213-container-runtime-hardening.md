# Issue 213: Container runtime hardening

## Objective
- Limit what a compromised container can do: no privilege escalation, minimal Linux capabilities,
  read-only filesystems where possible, and no raw Docker socket for Alloy.

## Architecture Decisions
- `x-hardening` anchor on every service: `no-new-privileges`, `cap_drop: [ALL]`, `pids_limit: 512`.
  **No capabilities are added back anywhere.**
- `postgres`: runs directly as `999:999` (the data dir is already owned by 999), so the root
  entrypoint, the gosu privilege drop and the caps the plan expected (`CHOWN`, `SETUID`, ...) aren't needed.
  Read-only root, tmpfs `/tmp` + `/var/run/postgresql`. Tested first on a fresh volume (initdb) and on
  a copy of the real volume, then applied after `make db-backup`. Row counts were identical.
- `api`: read-only root, tmpfs `/tmp`, `HOME=/tmp` so library caches (yfinance via platformdirs) are
  writable; `./data` stays rw. `api-dev` gets the same caps/no-new-privileges but a writable root,
  because the tools write caches.
- `loki` (10001), `grafana` (472): read-only root + tmpfs `/tmp`; data volumes rw.
- `alloy`: now `473:473` (the image defaulted to root). Read-only root. `--storage.path` restored
  (the old `command:` override had dropped it) onto a new `alloy-data` volume, so log positions survive restarts.
- **Docker socket proxy**: `tecnativa/docker-socket-proxy:v0.5.0` (mature, 6 HIGH / 0 CRIT vs
  wollomatic 1.13.1's 8 / 2) is the only container with the socket. It allows `CONTAINERS`,
  `NETWORKS`, `EVENTS`, `PING`, `VERSION`; `POST: 0`. It runs as root (to open the socket) but with no
  caps and a read-only root, on `docker-api` (`internal: true`, no egress), which only Alloy joins.
- Networks: postgres + api stay on the project `default` network (the MCP server joins it);
  `observability` holds loki/grafana/alloy.
- Deviation from plan: no memory limits. Ingestion (pandas) and Grafana have spiky memory, and a
  wrong cap would OOM-kill the DB or API. `pids_limit` covers the fork-bomb case.

## Acceptance Criteria
- [x] `docker inspect`: `no-new-privileges`, `CapDrop: [ALL]`, `CapAdd: []` on all 6 services; read-only root on all.
- [x] Only `docker-socket-proxy` mounts `/var/run/docker.sock`. Through it, `GET /containers/json` and
      `/events` return 200, while `/images/json`, `/secrets`, `/info`, `POST /containers/create`, `.../stop` and
      `DELETE` return 403. `docker-api` has no egress.
- [x] `make up`, `make observability-smoke` (log line found in Loki), browser login → `/wealth`, and
      API writes to `/tmp` + `/app/data` all work; root fs writes are blocked.
- [x] From the `observability` network, Postgres is unreachable; from `default` (MCP path), it is reachable.
- [x] `make lint`, `make typecheck`, `make test-backend` (439 passed).

## How To Test
- `make db-backup`, then `make up && make observability-up && make observability-smoke`.
- Upload a statement in the UI; confirm logs appear in Grafana.

<!-- IMMUTABLE_PLAN_END -->

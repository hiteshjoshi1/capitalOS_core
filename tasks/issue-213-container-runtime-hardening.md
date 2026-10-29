# Issue 213: Container runtime hardening (planned)

## Objective
- Limit what a compromised container can do: no privilege escalation, minimal Linux capabilities,
  read-only filesystems where possible, and no raw Docker socket for Alloy.

## Architecture Decisions
- All services: `security_opt: ["no-new-privileges:true"]`, `cap_drop: [ALL]`, plus `pids_limit` and
  a memory limit.
- Per-service caps and filesystems (each to be confirmed by testing):
  - `api`: no caps needed (already non-root). `read_only: true` + `tmpfs: /tmp`; `./data` stays rw.
  - `postgres`: the entrypoint switches users via gosu, so add back `CHOWN, SETUID, SETGID,
    DAC_OVERRIDE, FOWNER`. Test on a **copy** of the volume first, with `make db-backup` before any switch.
  - `loki`, `grafana`: run as their image users; `read_only: true` + tmpfs `/tmp`, data volumes rw.
- **Alloy and the Docker socket:** Alloy currently mounts `/var/run/docker.sock` (read-only, but
  that's still near-root on the host). Put a socket proxy in front of it
  (`tecnativa/docker-socket-proxy`, digest-pinned) allowing only `CONTAINERS=1` + `GET`, on an
  internal network. Alloy's `discovery.docker`/`loki.source.docker` point at `tcp://socket-proxy:2375`.
- Networks: split into `backend` (postgres, api) and `observability` (loki, grafana, alloy,
  socket-proxy) so Grafana/Alloy can't reach Postgres. Mark internal networks `internal: true`
  where nothing needs egress.
- Free: compose settings plus an open-source proxy image.

## Acceptance Criteria
- [ ] `docker inspect` shows `NoNewPrivileges`, `CapDrop: [ALL]` on every service.
- [ ] No container mounts `/var/run/docker.sock` except the proxy.
- [ ] `make up`, upload ingest (writes `data/raw`), `make observability-smoke`, and live-reload all work.
- [ ] From the grafana container, `postgres:5432` is unreachable.

## How To Test
- `make db-backup`, then `make up && make observability-up && make observability-smoke`.
- Upload a statement in the UI; confirm logs appear in Grafana.

<!-- IMMUTABLE_PLAN_END -->

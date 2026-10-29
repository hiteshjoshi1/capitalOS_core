# Issue 212: Replace the Postgres MCP server with Google MCP Toolbox + a read-only role

## Objective
- The `capitalos-postgres` MCP server ran `crystaldba/postgres-mcp:latest`: unpinned, no image or
  PyPI release since 2025-05-16 (0.3.0), and **214 HIGH / 12 CRITICAL** fixable findings (Trivy,
  2026-10-29). It connected as `capitalos`, a **superuser**; `--access-mode=restricted` was the only guard.
- Move to a maintained server and make read-only a property of the database role, not the server.

## Architecture Decisions
- **Google MCP Toolbox** (`googleapis/mcp-toolbox`, Apache-2.0) was chosen over DBHub and Postgres
  MCP Pro. It releases about every 2 weeks, has the richest Postgres toolset (29 tools: SQL, query plans,
  locks, bloat, index/table/query stats), the fewest findings (13 HIGH / 1 CRIT), and runs as a nonroot
  Go binary with telemetry off unless flags enable it. Pinned to **1.14.0** (2026-10-08), the newest
  release at least two weeks old.
- `tools/Dockerfile` is the registry of images used outside compose (Toolbox, Trivy). Dependabot's
  `docker` ecosystem watches `/tools`; `scripts/tool-image.sh <stage>` reads a reference for the
  wrapper, the Makefile and CI. This is the groundwork for issue 211's digest pinning.
- `scripts/mcp-postgres.sh` keeps its container cleanup and reaping and runs Toolbox with the compose
  hardening (`--read-only`, `--cap-drop ALL`, `no-new-privileges`, `--pids-limit 128`). Credentials
  are passed as env vars, never argv; the password comes from `.env` (`MCP_DB_PASSWORD`).
- **`capitalos_mcp_ro` role** (`scripts/db-create-mcp-role.sql`, via `make db-create-mcp-role`, idempotent):
  - `default_transaction_read_only = on`, and no write grants at all, so writes fail even inside an
    explicit `BEGIN READ WRITE`.
  - `statement_timeout 30s`, `idle_in_transaction_session_timeout 60s`, connection limit 5.
  - `SELECT` on all tables, including future tables via default privileges, **except
    `user_credentials` and `auth_sessions`**.
  - `pg_monitor` for Toolbox's diagnostics.
- The MCP image is scanned report-only in `make security-scan` and the CI `compose-images` matrix
  (we don't build it).

## Acceptance Criteria
- [x] Over stdio MCP: `initialize` → Toolbox 1.14.0, `tools/list` → 29 tools, `execute_sql` read → 597 txns.
- [x] `INSERT` → read-only error; `BEGIN READ WRITE; INSERT` → permission denied; `SET
      default_transaction_read_only=off` and `COMMIT; INSERT` → still blocked; `user_credentials` → permission denied.
- [x] No leftover MCP containers after the client exits; 0 probe rows written.
- [x] Local override updated (`claude mcp`): no superuser `DATABASE_URI`; `claude mcp get` → Connected.
- [x] `crystaldba/postgres-mcp:latest` removed locally.

## How To Test
- `make db-create-mcp-role`, restart Claude Code, then ask the `capitalos-postgres` tools for a row count.

<!-- IMMUTABLE_PLAN_END -->

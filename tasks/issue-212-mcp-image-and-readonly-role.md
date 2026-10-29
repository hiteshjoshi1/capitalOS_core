# Issue 212: Self-built MCP image and a read-only DB role (planned)

## Objective
- The `capitalos-postgres` MCP server runs `crystaldba/postgres-mcp:latest`, which is unpinned, last
  published 2025-05-16 (0.3.0), and has **214 HIGH / 12 CRITICAL** fixable findings (Trivy,
  2026-10-29). It connects to the real database as the owner role.
- Upstream publishes no newer image or PyPI release (repo still active), so pulling won't fix it.

## Architecture Decisions
- Build our own image: `tools/mcp-postgres/Dockerfile` = `python:3.12-slim` (fresh base, digest-pinned
  per issue 211) + `pip install postgres-mcp==0.3.0` from a `requirements.txt` there, then uninstall
  pip and run as non-root. Dependabot `pip` + `docker` entries for `/tools/mcp-postgres` track both
  the package and the base.
- `scripts/mcp-postgres.sh` runs the locally built tag (`capitalos-mcp-postgres:0.3.0`) and builds it
  on first use if missing. Container cleanup logic is unchanged.
- Add it to `make security-scan` and the CI `compose-images` matrix (**fail** on it, since we build it).
- **Least privilege:** a `capitalos_mcp_ro` role with `CONNECT` + `USAGE` on the schema +
  `SELECT` on all tables (and `ALTER DEFAULT PRIVILEGES` for future tables). Created by a
  `make db-create-mcp-role` target that reads the password from `.env` (`MCP_DB_PASSWORD`), not a
  migration, so no secret lands in git. `DATABASE_URI` in the local MCP override uses that role.
  Keep `--access-mode=restricted` as a second layer.

## Acceptance Criteria
- [ ] MCP image: 0 fixable HIGH/CRITICAL; runs as non-root.
- [ ] MCP queries work; `INSERT`/`UPDATE` through MCP fail with permission denied (role, not just mode).
- [ ] Old `crystaldba/postgres-mcp:latest` image removed locally.

## How To Test
- Restart Claude Code; run a `SELECT count(*) FROM transactions` through the MCP tool.
- `psql` as `capitalos_mcp_ro`: `INSERT ...` → `permission denied`.

<!-- IMMUTABLE_PLAN_END -->

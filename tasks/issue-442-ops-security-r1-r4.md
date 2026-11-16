# Issue #442: ops & security fixes from review #431 (R1–R4)

- **R1 MCP network:** `scripts/mcp-postgres.sh` takes the network from the DB container (`make print-db-container` →
  its `*_default` network); `.mcp.json` no longer hard-codes `capitalos_default`. `make mcp-check` (initialize + SELECT).
  Checked against the real stack: `MCP ok: accounts:10`.
- **R2 permissions:** `scripts/secure-perms.sh` (check / apply), `make secure-perms` (dry run; `APPLY=1`), warnings in
  `make status` and `make deploy`. Checked in this worktree's stack: with `data/` and `state/` at 700 the API container
  (uid 10001) still writes `data/` and reads `state/`. Tests: `scripts/test-secure-perms.sh` (5).
- **R3 Secure cookie:** D-119. Tests: `api/tests/test_cookie_secure.py` (5).
- **R4 observability:** deploy prints "Observability: not running (skipped)"; status shows "3/3 core containers up,
  observability off".

Post-deploy (main checkout): `make secure-perms` then `make secure-perms APPLY=1`; `make mcp-check`; restart the
Claude session so the MCP reloads `.mcp.json`.

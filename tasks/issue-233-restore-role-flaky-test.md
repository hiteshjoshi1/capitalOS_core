# Issue 233: db-restore stops before restoring data/ when the MCP role is missing; flaky AuthContext test

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/233

## Objective
- `make db-restore` completes, `data/` included, on a Postgres that has no `capitalos_mcp_ro` role
  (a new machine or stack), instead of stopping on the dump's GRANTs to it.
- On the real stack, where the role exists, MCP access still works after a restore.
- The AuthContext "tab becomes visible" test no longer depends on timing.

## Architecture Decisions
- D-56 (docs/decisions.md). The database part of the restore is one psql transaction:
  `pg_restore --clean --if-exists --no-privileges -f -`, then a reset of what the target's default
  privileges granted on the re-created tables, then the dump's own ACL statements (from
  `pg_restore --schema-only`, only its `ACL`/`DEFAULT ACL` entries) minus those that name a role the
  target lacks, then a check that every table's count equals the dump's snapshot (`.dump.counts`),
  then `COMMIT`. A pg_restore failure leaves no `COMMIT` (psql's session ends, rolled back).
  `data/` is swapped in only after the commit, as before.
- Left-out statements are listed ("Left out 62 privilege statement(s) for role(s) this Postgres
  doesn't have: capitalos_mcp_ro"); `make db-create-mcp-role` grants them later. A privilege
  statement of an unknown form fails the restore before anything changes, rather than being dropped.
- Found while testing: the old restore, on a stack with the MCP role, left `user_credentials` and
  `auth_sessions` readable by it (the re-created tables got the default privileges, and the dump
  has no ACL entry to take them back). The reset step fixes that.
- Flaky test: "demo" is in the DOM at commit, but the `visibilitychange` listener is attached by a
  passive effect that React's scheduler runs later (`setImmediate` in Node). RTL's `waitFor`
  returns after a `setTimeout(0)`, and under load that can come first, so the one dispatched event
  was missed. The test now waits for the listener to be attached. Two sibling tests with the same
  kind of assumption (WealthHistory movers fetch, CryptoWallets allowlist rows) wait too.

## Acceptance Criteria
- [x] Restore on a target without the role completes, `data/` restored, the role's grants named.
- [x] Existing guarantees: counts checked against the dump's snapshot (now inside the restore's
      transaction), `data/` moved aside to `data.pre-restore-<ts>`, an existing aside folder never
      overwritten, the signing key kept.
- [x] Target with the role: the dump's grants to it are applied; credential tables stay unreadable.
- [x] A test for a target without the role in `scripts/test-db-backup.sh` (`make lint`).
- [x] The flaky test waits for its condition; repeated runs and runs under load pass.

## How To Test
- `make lint` (runs `scripts/test-db-backup.sh`: 31 cases, with a fake Postgres for `restore()`).
- In a worktree: `make up`, `make db-restore BACKUP_FILE=<verified dump>` on the fresh stack (no MCP
  role) → "Left out N privilege statement(s) ... capitalos_mcp_ro", "counts identical", "Restored data/".
- Race reproduction (not committed): a vitest config whose first setup file wraps
  `globalThis.setImmediate` in a 20 ms `setTimeout` makes the old AuthContext test fail every time
  with "expected vi.fn() to be called 1 times, but got 0 times"; the fixed one passes.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `ship`
- Workflow Status: `shipped`
- Provider/Model: `claude/claude-opus-5-5`
- Last Updated: `2026-11-06`

## Deterministic Gate Results (Codex Mutable)
- Real restore, worktree stack, newest verified backup (2026-11-06 15:59), fresh stack without the
  role: the old command exits 1 ("errors ignored on restore: 62", all `role "capitalos_mcp_ro" does
  not exist`); the new restore exits 0: 62 tables, 31663 rows, counts identical to the snapshot
  (and an independent count diff afterwards), 62 privilege statements left out and named, data/
  restored: 56 files, all 52 recorded files present with their sha256; API health ok.
- Same, with the role and its default privileges present: 62 privilege statements applied, the role
  reads 60 tables and the schema, not `user_credentials`/`auth_sessions` (the old restore: readable).
- Flaky test: 30 parallel runs normal + 30 with the scheduler delay: all pass; full frontend suite
  6 times, 3 at once: 442/442 each; full suite with the scheduler delay 5 times: 442/442 each.

## Extra Files Changed (Codex Mutable)
- `web/src/__tests__/WealthHistory.test.tsx`, `web/src/__tests__/CryptoWallets.test.tsx` — reason:
  same timing assumption, found by running the suite with the scheduler delay.
- `CLAUDE.md`, `Makefile` (comment), `docs/decisions.md` — reason: restore behaviour documented (D-56).

# Issue 41: Verified, scheduled database backups with retention

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/41

## Objective
- Every backup of the real-data stack is **proven restorable**, made daily without anyone
  remembering, and kept for a bounded window. Inspired by InvestOS's D-78/D-79 backups.

## Architecture Decisions
- **Exact verification.** `pg_dump` runs with `--snapshot` from a `REPEATABLE READ` transaction
  that also takes every table's exact row count (`.counts`). The dump is restored into a scratch
  database (`--no-owner --no-acl --exit-on-error`); its counts must equal the snapshot's, table
  by table. Only then is `.verified` written; otherwise it's `.failed` with the reason (plus
  `.diff` / `.restore.log`).
  - *Rejected:* comparing with live counts taken after the dump. The schedulers write
    continuously, so that would produce false failures (measured: the snapshot had 200,550 rows
    while live grew to 201,900 during the backup).
- One `EXIT` trap cleans up the snapshot session, temp dir and scratch DB on every path. Dumps
  are written to `.part` and renamed only on success.
- **Old dumps** (no markers): `make db-backup-verify` reports them as `.restorable` (restore
  only, no counts to compare). Prune never touches them, so the 2026-08-28 dump, the only copy of
  that history, is safe.
- **Retention:** `make backup-prune [KEEP=14]` removes only backups this tool verified, beyond the
  newest KEEP (by verification time), plus failed attempts older than 7 days. The newest verified
  backup is never removed (KEEP ≥ 1).
- **Schedule:** a launchd agent (`com.capitalos.db-backup`, 03:00 daily, run on wake if missed)
  runs `make db-backup && make backup-prune` with an explicit PATH. Logs go to
  `backups/backup.log`. `make backup-status` shows the newest verified backup, the schedule and
  its last exit code.
- `db-wait` is now bounded (`DB_WAIT_SECONDS`, default 120). It used to loop forever, so a 03:00
  run with Docker down would have hung, and launchd never starts a second instance of a running job.

## Acceptance Criteria
- [x] A live backup restores into a scratch DB with identical counts (57 tables, 5,708 rows); the scratch DB is dropped.
- [x] A truncated dump → `pg_restore failed`, exit 1. Tampered counts → `row counts differ`, exit 1, with the diff.
- [x] Under concurrent inserts the backup still verifies exactly (snapshot consistency).
- [x] Prune (KEEP=2 on 5 verified + 1 old + 1 old-failed) keeps 2 and the old dump, and removes 3 + the failed one.
- [x] launchd job installed, run on demand (`make backup-now`), last exit 0, logged; `backup-status` shows it.
- [x] Docker/DB down → `db-wait` fails after the timeout with a hint, instead of hanging.

## How To Test
- `make db-backup && make backup-status`
- `make db-backup-verify BACKUP=backups/<file>.dump`
- `make backup-now`, then `tail backups/backup.log`

<!-- IMMUTABLE_PLAN_END -->

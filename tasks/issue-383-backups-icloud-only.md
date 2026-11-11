# Issue #383: one backup folder in iCloud Drive; works under launchd without listing

## Why
The 11 Nov 03:00 backup failed: under launchd macOS let `/bin/bash` create files in the personal
backup folder but refused the rename (`mv … .age.part → .age: Operation not permitted`) and listing.
In iCloud Drive the job may create, rename, delete, stat and read, but not list (#357).

Hitesh (2026-11-11): one backup folder, in iCloud Drive; nothing in personal folders; Claude Code is
denied Documents and Desktop.

## Change (D-105)
- `scripts/db-backup.sh`: a per-folder index, `.capitalos-index` (generalised from #357's off-site
  index). `dir_names` answers "which verified sets are here" from a listing when allowed (refreshing
  the index) and from the index otherwise; `index_add` records a new set (create, encrypt-existing);
  `index_refresh` rewrites it after prune. A pre-#383 `.capitalos-offsite-index` is adopted.
  `verified_sets` / `verified_newest_first` use it, so status, prune and encrypt-existing work
  where listing is refused. `BACKUP_TEST_UNLISTABLE`: `1`/`offsite`, `local`, `all`.
- `scripts/backup-env.sh` `backup_newest_verified` (deploy, `make status`, test instance): listing,
  else the index.
- `scripts/status.sh`, `scripts/test-instance.sh`: use `backup_newest_verified`.
- Docs: CLAUDE.md, `.env.example`, `docs/setup/backups.md`, `scripts/backup-schedule.sh` comment;
  no personal-folder default left.

## Tests
`scripts/test-db-backup.sh` (64): unlistable BACKUP_DIR: newest from the adopted index, verified sets,
create's index_add, status, prune by index, no-index warning (no empty index written), a listing
rebuilds the index; existing off-site tests on the new index name.

## Live check (after merge + deploy, main checkout)
`make backup-status` (Terminal: writes `.capitalos-index`), `make backup-now`, then `make backup-status`
(last exit 0, newest set from just now).

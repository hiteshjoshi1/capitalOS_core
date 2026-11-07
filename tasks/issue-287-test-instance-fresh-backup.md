# Issue 287: Test instance takes a fresh verified backup, and shows the copy's age

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/287

## Objective
- A test instance shows the real app's data as of the moment it's served (on 2026-11-07 it showed five
  sources overdue because it copied the 09:28 backup, before that day's uploads).

## Architecture Decisions
- `serve()` calls `fresh_dump`: `make db-backup` (verified, from the main checkout) and then the newest
  verified dump. `SKIP_BACKUP=1` reuses the newest verified one. A failed backup stops the serve.
- The dump is recorded in the state file (`data_from`). The TEST banner reads "data 15:10 today", and
  `make test-instance-status` prints the copy and a "Data drift" line when the real app's newest import
  is newer than the copy's (`import_jobs.created_at`, in the host's time zone, read-only queries).
- `BACKUP_CMD` / `REAL_DB_CONTAINER` / `HOST_TZ` can be overridden; the test uses a fake backup.

## Acceptance Criteria
- [x] Default: a fresh backup is taken and served; SKIP_BACKUP=1: the newest verified one, no backup.
- [x] A failed backup stops it, named.
- [x] Banner and status show the copy's time; status flags newer real imports.
- [x] `scripts/test-test-instance.sh`: 9 new checks (24 total).

## How To Test
- `scripts/test-test-instance.sh`
- Next `make test-instance PRS="…"`: the log shows "taking a fresh verified backup", and the banner shows its time.

<!-- IMMUTABLE_PLAN_END -->

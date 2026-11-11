# Issue #387: daily backup at 13:00 (configurable BACKUP_TIME)

## Goal
Hitesh, 2026-11-11: run the scheduled backup at 13:00, not 03:00 (the Mac is asleep at night; the
11 Nov run crawled through dark wakes for 45 minutes).

## Change
- `scripts/backup-env.sh`: `BACKUP_TIME` (HH:MM, 24-hour; environment, then `.env`, default 13:00),
  `backup_time_parse` / `backup_time`.
- `scripts/backup-schedule.sh`: `install` writes the time into the plist; new `plist` (print what
  install writes) and `time` (installed time); `status` shows the installed time and warns when it
  differs from `BACKUP_TIME`. `BACKUP_SCHEDULE_PLIST` points it at another plist (tests).
- "03:00 job" wording → "daily job" in scripts and docs; docs/setup/backups.md's hand-written plist
  replaced by `make backup-schedule`; `.env.example` documents `BACKUP_TIME`.

## Tests
`scripts/test-backup-schedule.sh` (in `make lint`): valid/invalid times, env/.env/default, plist
content, reading the time back. Never touches launchd.

## After deploy
`make backup-schedule` (reinstalls the job at 13:00), then `make backup-status`.

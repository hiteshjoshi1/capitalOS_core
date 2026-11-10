# Issue #357: Backups: encrypted off-site copy (iCloud Drive)

Built in the #356 branch/PR (Hitesh, 2026-11-10: iCloud Drive). Decision D-93.

- `BACKUP_OFFSITE_DIR` (main checkout's `.env`): after each backup, every verified encrypted set
  missing there is copied (sha256-compared, marker last); prune keeps the same retention there.
- Missing (iCloud Drive off) or unwritable folder: a warning, never a failed backup.
- `backup-status`: newest off-site copy, warning when missing or > 2 days old.
- `make backup-offsite-check`: newest off-site set copied to a temp dir, decrypted, full restore check.
- `make backup-offsite-sync`: copy what's missing now.
- macOS privacy: the 03:00 job is `/bin/bash` under launchd; `backup-status` flags a failed last run and
  "Operation not permitted"; fix = Full Disk Access for `/bin/bash`. A launchd probe on 2026-11-10 could
  write, list and read inside a new `~/Documents` subfolder (only listing `~/Documents` itself was refused);
  iCloud Drive was off, so it couldn't be probed.

## Verification
- `scripts/test-db-backup.sh`: no iCloud folder (warns, nothing created), copy of encrypted sets only
  (byte for byte), idempotent, unwritable folder warns, status (stale > 2 days, missing), prune off-site.
- By hand: `make db-backup` with an off-site dir (with a space in its path), `backup-offsite-check`,
  `backup-status`, and a backup with the folder missing (warns, exit 0).

# Issue #357: Backups: encrypted off-site copy (iCloud Drive)

Built in the #356 branch/PR (Hitesh, 2026-11-10: iCloud Drive). Decision D-96.

- `BACKUP_OFFSITE_DIR` (main checkout's `.env`): after each backup, every verified encrypted set
  missing there is copied (sha256-compared, marker last); prune keeps the same retention there.
- Missing (iCloud Drive off) or unwritable folder: a warning, never a failed backup.
- `backup-status`: newest off-site copy, warning when missing or > 2 days old.
- `make backup-offsite-check`: newest off-site set copied to a temp dir, decrypted, full restore check.
- `make backup-offsite-sync`: copy what's missing now.
- macOS privacy: the 03:00 job is `/bin/bash` under launchd. Launchd probes on 2026-11-10: in a new
  `~/Documents` subfolder it could write, list and read (only listing `~/Documents` itself was refused); in
  iCloud Drive it could cp, mv, rm, stat and `test -e` files, but NOT list the folder. So nothing lists the
  off-site folder: the sync goes by the local set names and keeps `.capitalos-offsite-index` there (atomic
  tmp+mv); prune, status and offsite-check read it. No Full Disk Access (Hitesh: too broad for /bin/bash).
- Wrong key (found trialling on the test instance): a decrypt failure says "cannot decrypt … with <key>:
  wrong or missing key" and writes no marker or log next to the set; `verify <set>.dump.age` is the set.

## Verification
- `scripts/test-db-backup.sh`: no iCloud folder (warns, nothing created), copy of encrypted sets only
  (byte for byte), idempotent, unwritable folder warns, status (stale > 2 days, missing), prune off-site.
- By hand: `make db-backup` with an off-site dir (with a space in its path), `backup-offsite-check`,
  `backup-status`, and a backup with the folder missing (warns, exit 0).

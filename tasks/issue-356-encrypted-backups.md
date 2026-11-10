# Issue #356: Backups encrypted (age), kept outside the repo

## Goal
Backup sets hold every raw statement. Encrypt them, and keep them out of the repo in
`~/Documents/CapitalOS_backups`, without breaking verify, restore, retention, deploy or the test
instance. Off-site copy is #357.

## Plan
- `scripts/age-tool.sh`: age v1.3.2 host binary, sha256-pinned per platform (GitHub asset digests);
  `make host-tools` installs it.
- `scripts/backup-env.sh`: one place resolving BACKUP_DIR / BACKUP_AGE_RECIPIENT / BACKUP_AGE_IDENTITY
  (env, then .env, then defaults); `.env`'s BACKUP_DIR only in the main checkout.
- `scripts/db-backup.sh`: create in a private temp dir, verify, then seal (encrypt to `.age`, markers
  plain, `.verified` last, round-trip check when the private key is present); verify/restore/open
  decrypt into a private temp dir; prune and status know `.age`; `key-init`; `encrypt-existing`.
- deploy.sh, status.sh, test-instance.sh read the backup dir from backup-env.sh; the test instance
  restores from `db-backup.sh open`.
- D-95.

## Verification
- `scripts/test-db-backup.sh`: seal, open (byte-for-byte, 700 dir), encrypted restore end to end,
  missing key (restore unchanged, verify leaves markers), wrong key, encrypt-existing dry run / apply
  (incl. an unmarked old dump), prune of an encrypted set, backup-dir resolution (main vs worktree vs env).
- Manual, on the worktree stack with a throwaway key: `make db-backup` (encrypted), `db-backup-verify`,
  `backup-status`, `db-restore`, `backup-encrypt-existing` dry run and APPLY=1.

## Post-deploy (main checkout)
1. `make host-tools` (installs age), 2. `make backup-key-init`, save the private key in the password
manager, 3. add `BACKUP_DIR=~/Documents/CapitalOS_backups` to `.env`, 4. `make db-backup`,
5. `make backup-encrypt-existing` then `APPLY=1`, 6. `make backup-now` and check the log (launchd and
~/Documents: macOS privacy controls).

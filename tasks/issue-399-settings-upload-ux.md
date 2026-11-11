# Issue #399: Settings, Data Hub & uploads (UX U22, U23, U24, U26, U27)

From the UX sweep #354, okayed by Hitesh on 2026-11-11 for sprint 22.

## What changed
- **U22 Backup status in the app (D-111).**
  - `scripts/db-backup.sh` writes `state/backup-status.json` after every backup (with the run's result), prune and `make backup-status`. The file holds no paths or keys.
  - `./state` is mounted read-only into the API, which serves `GET /operations/backup-status`.
  - Data Hub shows "Last verified backup 13:00 today · next 13:00 tomorrow · iCloud Drive". It turns amber after 2 days, and red after 7 days or a failed run.
  - The Inbox gets a `backup_stale` item when the backup is stale, or the all-good line "Backup verified N hours ago" when it isn't.
- **U23 One theme control.** The Settings "Appearance" card and its stale sentence are gone. The theme toggle is in the header, and in the user menu on a phone.
- **U24 Settings facts.** A new "How CapitalOS counts" card, read-only:
  - when a month closes (`SNAPSHOT_DAY`);
  - the default upload cadence (`UPLOAD_STALE_DAYS`), with a link to Data Hub → Accounts & sources for each source's own schedule;
  - the currency list from `/currencies`, and which currencies the app can value in.
  - Source: `GET /settings/facts`.
  - Stale thresholds stay read-only here: they are server settings and per-source cadences, not per-user settings.
- **U26 Upload wording.** The card now says "Upload a statement"; the dropzone already lists .csv · .xls · .xlsx.
- **U27 Account picker.**
  - The picker is grouped by kind (Bank accounts, Credit cards, Brokers, Funds, Exchanges, Wallets, Loans, Other), with closed accounts last.
  - Choosing a file calls `POST /ingest/detect`, which reads the format and stores nothing.
  - If exactly one open account fits (or the statement's account number is linked to one) and none is chosen yet, it is pre-selected. A line says what the file looks like and whether the chosen account fits. It never changes a choice.

## After deploy
- `make backup-status` once in the main checkout, which writes the first status file. The 13:00 job keeps it current.
- `make deploy` recreates the API with the new `./state` mount.

## Tests
- Backend: `api/tests/test_settings_upload_399.py` (status reading, staleness, next run, Inbox item, facts, detect).
- Script: `scripts/test-db-backup.sh` (status file: content, no paths, keeps last run, failed run, empty, icloud).
- Web: `web/src/__tests__/settingsUpload399.test.tsx`; the Ingest tests are updated for the new title and the detect call.

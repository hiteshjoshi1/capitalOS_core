# Backing up your database

CapitalOS stores everything — accounts, transactions, portfolio positions,
crypto wallets, everything — in a single Postgres database running inside a
Docker container, in a Docker-managed volume. **Docker volumes are not
backups.** A `docker compose down -v`, a container-name collision with
another checkout on the same machine, or any other slip deletes that volume
permanently with no undo. If you only have one copy of your data and it
lives exclusively inside Docker, one mistake — yours or a tool's — can lose
all of it.

Back up regularly, to a plain file *outside* Docker's managed storage, so a
normal OS-level backup tool (Time Machine, a cloud sync folder, anything)
can pick it up.

## Manual backup / restore

```bash
make db-backup
```

Writes a timestamped `pg_dump` (custom format) to `backups/` at the repo
root — a plain file, gitignored, untouched by anything Docker does to its
own volumes — and, next to it, `capitalos_<timestamp>.data.tar.gz`: the
contents of `data/` (the raw statements and broker reports the database
points at; the API's signing key `data/.auth_secret` is left out). Both are
verified: the dump is restored into a scratch database (exact row counts),
the archive is unpacked and every file a restored row records must be there
with the sha256 the database has for it. Only then is a `.verified` marker
written. `make backup-data-check` runs the file check against the live
database and `data/` without making a backup.

```bash
make db-restore BACKUP_FILE=backups/capitalos_20260101_120000.dump
```

Restores that file into the running Postgres container, after an explicit
`yes` confirmation (this overwrites the current database — it's meant for
disaster recovery, not routine use), and `data/` from the matching
`.data.tar.gz`. The current `data/` is not deleted: it is moved to
`data.pre-restore-<timestamp>/`. The API is stopped during the restore and
started again afterwards. A dump from before data archives existed restores
the database only, with a warning.

`make backup-prune` keeps every verified backup from the last 14 days, the
first verified backup of each of the last 12 months, and the newest one; a
dump and its data archive are removed together. `make backup-prune DRY_RUN=1`
lists what it would remove. Dumps without a `.verified` marker are never
pruned.

## Automate it

Backups you have to remember to run don't help when you need them. Set up a
daily scheduled job:

**macOS (launchd)** — create `~/Library/LaunchAgents/com.capitalos.dbbackup.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.capitalos.dbbackup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/make</string>
    <string>-C</string>
    <string>/absolute/path/to/capitalOS</string>
    <string>db-backup</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>2</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/capitalos-db-backup.log</string>
  <key>StandardErrorPath</key><string>/tmp/capitalos-db-backup.log</string>
</dict>
</plist>
```

Then `launchctl load ~/Library/LaunchAgents/com.capitalos.dbbackup.plist`.
Runs daily at 2am; requires Docker Desktop to be running at that time.

**Linux / cron** — `crontab -e`:

```
0 2 * * * cd /absolute/path/to/capitalOS && make db-backup >> /tmp/capitalos-db-backup.log 2>&1
```

## Make sure the backups themselves survive

`backups/` is a normal directory of plain files, so:

- **Time Machine** (macOS) will pick it up automatically as long as it's not
  excluded and your Mac is on/awake at some point during the backup window.
- Even better: point the backup at (or sync it into) cloud storage —
  iCloud Drive, Dropbox, a private git-less S3 bucket, whatever you already
  trust — so a single-machine failure doesn't take out both the live DB and
  its backups. `backups/` is gitignored on purpose: back it up somewhere
  that isn't this git repo, since these dumps contain your real financial
  data.
- Periodically actually test a restore (e.g. into a throwaway container) —
  an untested backup is a hope, not a backup.

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

## Encrypted, and outside the repo (#356)

Backups hold every statement you uploaded, so they are encrypted with
[age](https://age-encryption.org) and kept outside the checkout.

```bash
make host-tools            # installs the pinned age (sha256-checked) into ~/.capitalos/age
make backup-key-init       # once: creates the key pair
```

`backup-key-init` writes the **private key** to `~/.capitalos/backup/age-identity.txt`
(chmod 600, outside the repo) and adds the **public key** to `.env` as
`BACKUP_AGE_RECIPIENT`. Save the private key somewhere off this machine now (a
password manager's secure note): without it, no encrypted backup can be restored,
which is exactly the situation after a lost or dead Mac.

Then set where backups go, in the main checkout's `.env`. One folder in iCloud Drive (#383):
it is the Mac's copy and, synced by iCloud, the off-site one too. In Finder, right-click it and
choose **Keep Downloaded** so macOS never swaps old sets for cloud-only placeholders.

```
BACKUP_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/CapitalOS_backups
```

Don't put backups in your personal folders (Documents, Desktop): under launchd macOS refused
the 03:00 job renames there (11 Nov 2026), and Claude Code is denied those folders.

From then on `make db-backup` makes and verifies the set in a private temp dir, then
stores `capitalos_<ts>.dump.age`, `.dump.counts.age` and `.data.tar.gz.age` in
`BACKUP_DIR`; the plaintext is deleted. Only the public key is needed to make a backup.
The `.verified` / `.failed` markers stay plain (dates and row counts, nothing from your
data), so `make backup-status` and `make backup-prune` work without the private key.
`make db-backup-verify`, `make db-restore` and the test instance decrypt with the private
key (`BACKUP_AGE_IDENTITY` points elsewhere if you keep it elsewhere). Use the set's
logical name, without `.age`:

```bash
make db-restore BACKUP_FILE="$HOME/Library/Mobile Documents/com~apple~CloudDocs/CapitalOS_backups/capitalos_20261110_030000.dump"
```

Move the older plain sets over (each file is decrypted back and compared before its
plaintext is deleted):

```bash
make backup-encrypt-existing            # dry run: lists what it would do
make backup-encrypt-existing APPLY=1    # SRC_DIR=<dir> for a folder other than ./backups
```

Worktrees, CI and the test instance keep `./backups` (a `BACKUP_DIR` in `.env` counts only
in the main checkout), and without `BACKUP_AGE_RECIPIENT` backups are plain, as before.

## A second copy (#357, optional)

With `BACKUP_DIR` in iCloud Drive (#383) the sets are already off the Mac, and
`BACKUP_OFFSITE_DIR` stays unset. It remains for a second folder elsewhere, e.g. an external
drive, in the main checkout's `.env`:

```
BACKUP_OFFSITE_DIR=/Volumes/<drive>/CapitalOS_backups
```

After every backup, each verified **encrypted** set the off-site folder lacks is copied
there (compared by sha256; the `.verified` marker last), so a missed day or a late-enabled
iCloud catches up. Plain sets never go off-site. `make backup-prune` keeps the same retention
there. A missing folder (iCloud Drive not turned on) or one that can't be written is a
loud warning in the log, never a failed backup: the local set is already safe.

- `make backup-status`: the newest off-site copy and its age; a warning when it's missing or
  older than 2 days.
- `make backup-offsite-check`: copies the newest off-site set to a private temp dir, decrypts
  it and runs the full restore check (do it monthly; nothing off-site is written).
- `make backup-offsite-sync`: copy what's missing now.

### macOS privacy (the 03:00 job)

The schedule runs `/bin/bash` under launchd. macOS protects iCloud Drive (and your personal
folders) differently for it than for Terminal. Probed on 2026-11-10/11: in iCloud Drive the job
may create, rename, delete, stat and read files by name, but listing the folder is refused
("Operation not permitted"). So every backup folder keeps an index, `.capitalos-index` (one set
name per line, written atomically): a new set is added to it, prune rewrites it, and
`backup-status`, prune, `make deploy`, `make status` and the test instance read it whenever the
folder can't be listed. Where listing works (Terminal) the index is rebuilt from the listing. A
folder that was the off-site copy before #383 keeps its `.capitalos-offsite-index`, which is read
until the first rewrite. With no index and no listing, the job says so: run `make backup-status`
once in Terminal to create it.

No permission grant is needed. Don't give `/bin/bash` Full Disk Access: it would open the whole
disk to every bash script. If `backup-status` flags "Operation not permitted", run
`make backup-now` in Terminal to see whether it works there, and report what the log says.

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

The backup folder is a normal directory of files (encrypted, see above), so:

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

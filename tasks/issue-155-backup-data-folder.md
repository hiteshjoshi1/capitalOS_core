# Issue 155: Deploy and backups: no --reload on the real stack, DB-backed /health, back up data/ raw files

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/155

## Objective
- New code reaches the real-data API only after `make deploy` has built the image and run the migrations (#130 finding 9.3).
- `/health` says whether the database answers and whether its migrations match the checkout's files.
- Every backup also carries `data/` (raw statements, IBKR Flex XMLs), verified against the hashes the database recorded, and a restore brings both back (#130 3.6, 9.4).

## Architecture Decisions
- Real stack: no code bind mount, no `--reload`; the API runs the code baked into the runtime image. Worktrees and the test instance keep the mount + reload (`docker-compose.isolated.yml`). Rejected: pausing reload during deploy (the reloader still sees a half-applied fast-forward unless the API is stopped, i.e. downtime for every deploy, and any `git pull` outside deploy would still go live).
- On a failed migration deploy resets the code AND rebuilds the image from it, so a later `make up` can't start code whose migrations didn't run; migrations of the batch that did apply are named (D-13 keeps them).
- `/health`: `SELECT 1` + `MAX(filename)` of `schema_migrations`; latest file from `./migrations` mounted read-only at `/app/migrations`. 200 + `status: ok` when the DB answers (migration state is reported, not a failure); 503 + `status: error` when it doesn't.
- Data archive = contents of `data/` minus `data/.auth_secret` (the API's signing key stays out of backups; a restore keeps the current one), taken right after the dump: files are written before their rows and never deleted, so every dumped row's file is in it.
- A row "records a file" when it has a path and a 64-hex sha256. Rows without one are counted, not failed: an upload whose copy failed (empty path and hash) and the demo seed's history rows (made-up paths, md5 placeholders). Paths map `/app/data/<rel>` or `data/<rel>` to `<rel>`; anything else (or `..`) fails.
- Verify checks the data against the rows of the restored scratch DB (exactly the dump's content). A pre-#155 dump without an archive: DB part checked, markers left as they are (a `.verified` needs both parts).
- Restore: DB first (data/ untouched if it fails), then the staged archive swapped in; the current `data/` is moved to `data.pre-restore-<ts>/`. The API is stopped during the restore (its bind mount must be re-made onto the new folder).
- Retention: every verified set since today-14d, the first verified set of each of the last 12 calendar months (this one included), and always the newest set; names without a timestamp kept; unmarked dumps never pruned (D-11).

## Acceptance Criteria
- [x] `capitalos_<ts>.data.tar.gz` next to each dump; verification unpacks it and checks every recorded file's sha256; missing/changed file fails; `.verified` only when both parts pass.
- [x] `make db-restore` restores both; the current `data/` is moved aside; an old dump without an archive restores with a warning.
- [x] Retention per the owner's comment, dump + archive pruned together, `DRY_RUN=1`.
- [x] Real stack runs without reload; deploy order proven on an isolated stack in the real stack's shape.
- [x] `/health` checks the DB and reports applied vs latest migration; `status: ok` kept.

## How To Test
- `scripts/test-db-backup.sh` (also run by `make lint`): data check, archive round trip, restore swap, retention, prune.
- `scripts/test-checkout-guard.sh`: compose config of the real-data stack has no `--reload` and no code mount; a worktree has both.
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_health.py tests/test_contracts.py`.
- On a worktree stack: `make db-seed-demo`, add synthetic rows + files, `make db-backup`, `make backup-data-check`, `echo yes | make db-restore BACKUP_FILE=...`.

<!-- IMMUTABLE_PLAN_END -->

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make verify`
- `typecheck`: pass — `make verify`
- `tests`: pass — `make verify` (backend + frontend), `scripts/test-db-backup.sh` 22/22 (macOS and Linux GNU tools), `scripts/test-checkout-guard.sh` 18/18
- `e2e`: skip
- `api-smoke`: pass — isolated stack `/health` (200 ok, 503 with Postgres stopped)

## Extra Files Changed (Codex Mutable)
- `scripts/test-instance.sh` — reason: the test instance unpacks the backup set's data archive too, so raw-file rebuilds work on the copy.
- `AGENTS.md`, `CLAUDE.md`, `ReadMe.md`, `docs/setup/backups.md` — reason: describe the no-reload real stack, data archives, restore and retention.

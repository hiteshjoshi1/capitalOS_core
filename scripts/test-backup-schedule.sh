#!/bin/bash
# Tests for the daily backup's time (#387): BACKUP_TIME parsing and the plist the schedule writes.
# Never touches launchd or the real LaunchAgents plist (BACKUP_SCHEDULE_PLIST points at a temp file).
set -uo pipefail
src=$(cd "$(dirname "$0")/.." && pwd)
pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok   $1"; }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# shellcheck source=backup-env.sh
. "$src/scripts/backup-env.sh"

for t in 13:00:"13 0" 03:05:"3 5" 0:00:"0 0" 23:59:"23 59" 7:30:"7 30"; do
  in=${t%%:*}:$(echo "$t" | cut -d: -f2) want=${t##*:}
  [ "$(backup_time_parse "$in")" = "$want" ] && ok "time: $in -> $want" || bad "time: $in gave '$(backup_time_parse "$in")', want '$want'"
done
for in in 24:00 12:60 1pm 13 13:0 "" " 13:00" 13:00x -1:00; do
  backup_time_parse "$in" >/dev/null && bad "time: '$in' should be refused" || ok "time: '$in' refused"
done

# Where the time comes from: the environment, then the repo's .env, then 13:00.
repo=$tmp/repo; mkdir -p "$repo"
[ "$(BACKUP_TIME= backup_time "$repo")" = 13:00 ] && ok "time: default 13:00" || bad "default: $(BACKUP_TIME= backup_time "$repo")"
echo "BACKUP_TIME=14:15" >"$repo/.env"
[ "$(BACKUP_TIME= backup_time "$repo")" = 14:15 ] && ok "time: from .env" || bad "from .env: $(BACKUP_TIME= backup_time "$repo")"
[ "$(BACKUP_TIME=09:45 backup_time "$repo")" = 09:45 ] && ok "time: the environment wins over .env" || bad "env over .env"

# The plist `install` would write, and reading the time back from it.
plist=$tmp/job.plist
BACKUP_TIME=13:00 "$src/scripts/backup-schedule.sh" plist >"$plist"
grep -q '<key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer>' "$plist" &&
  ok "plist: StartCalendarInterval 13:00" || bad "plist: $(grep -A1 StartCalendar "$plist")"
grep -q 'make -s db-backup &amp;&amp; make -s backup-prune' "$plist" && ok "plist: runs backup then prune" || bad "plist: command"
[ "$(BACKUP_SCHEDULE_PLIST=$plist "$src/scripts/backup-schedule.sh" time)" = 13:00 ] &&
  ok "time: read back from the plist" || bad "plist time: $(BACKUP_SCHEDULE_PLIST=$plist "$src/scripts/backup-schedule.sh" time)"
BACKUP_TIME=7:05 "$src/scripts/backup-schedule.sh" plist >"$plist"
[ "$(BACKUP_SCHEDULE_PLIST=$plist "$src/scripts/backup-schedule.sh" time)" = 07:05 ] &&
  ok "time: 7:05 written and read back as 07:05" || bad "7:05 round trip"
out=$(BACKUP_TIME=1pm "$src/scripts/backup-schedule.sh" plist 2>&1); rc=$?
[ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "BACKUP_TIME=1pm is not a 24-hour HH:MM time" &&
  ok "plist: a bad BACKUP_TIME is refused with a clear message" || bad "bad time: rc=$rc $out"
[ -z "$(BACKUP_SCHEDULE_PLIST=$tmp/none.plist "$src/scripts/backup-schedule.sh" time)" ] &&
  ok "time: nothing when no plist is installed" || bad "no plist"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]

#!/bin/bash
# Daily verified backup via launchd (issue #41):
#   backup-schedule.sh install     run `make db-backup && make backup-prune` daily at BACKUP_TIME
#   backup-schedule.sh uninstall   remove the job
#   backup-schedule.sh status      is it installed, at what time, its last exit, the last log lines
#   backup-schedule.sh run         run it now, exactly as launchd does
#   backup-schedule.sh plist       print the plist `install` would write (no launchd involved)
#   backup-schedule.sh time        the time the installed job runs at (HH:MM), from its plist
# BACKUP_TIME (HH:MM, 24-hour, local time; scripts/backup-env.sh: environment, then .env) defaults
# to 13:00 (#387): the Mac is usually asleep at night. A Mac that is asleep at that time runs the
# job when it wakes. If Docker isn't running the backup fails, and that failure is logged and shown
# by `make backup-status`. Changing BACKUP_TIME takes effect on the next `make backup-schedule`.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=backup-env.sh
. "$REPO/scripts/backup-env.sh"
LABEL=com.capitalos.db-backup
PLIST=${BACKUP_SCHEDULE_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}
LOG="$REPO/backups/backup.log"
# launchd starts with a minimal PATH; Docker Desktop and Homebrew live here.
JOB_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

# The configured time as "H M", or exit with a clear message.
configured_time() {
  local t hm
  t=$(backup_time "$REPO")
  hm=$(backup_time_parse "$t") || { echo "BACKUP_TIME=$t is not a 24-hour HH:MM time (e.g. 13:00)" >&2; exit 2; }
  echo "$hm"
}

print_plist() {  # <hour> <minute>
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-c</string>
    <string>cd "$REPO" &amp;&amp; echo "=== \$(date) scheduled backup" &amp;&amp; make -s db-backup &amp;&amp; make -s backup-prune</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$JOB_PATH</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
}

# HH:MM from an installed plist's StartCalendarInterval, or nothing (plain text parse: works
# without plutil, so the tests run on Linux too).
plist_time() {  # <plist>
  local h m
  [ -f "$1" ] || return 0
  h=$(tr -d '\n' <"$1" | sed -n 's#.*<key>Hour</key>[[:space:]]*<integer>\([0-9]*\)</integer>.*#\1#p')
  m=$(tr -d '\n' <"$1" | sed -n 's#.*<key>Minute</key>[[:space:]]*<integer>\([0-9]*\)</integer>.*#\1#p')
  [ -n "$h" ] && printf '%02d:%02d\n' "$h" "${m:-0}"
  return 0
}

case "${1:-}" in
  install)
    hm=$(configured_time); read -r hour minute <<<"$hm"
    mkdir -p "$(dirname "$PLIST")" "$REPO/backups"
    print_plist "$hour" "$minute" >"$PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed $LABEL: daily at $(plist_time "$PLIST"), log $LOG"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL"
    ;;
  plist)
    hm=$(configured_time); read -r hour minute <<<"$hm"
    print_plist "$hour" "$minute"
    ;;
  time)
    plist_time "$PLIST"
    ;;
  status)
    if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
      last=$(launchctl print "gui/$(id -u)/$LABEL" | sed -n 's/^[[:space:]]*last exit code = //p' | head -1)
      at=$(plist_time "$PLIST")
      echo "Schedule: installed (daily at ${at:-unknown time}), last exit $last"
      want=$(backup_time "$REPO")
      if hm=$(backup_time_parse "$want") && [ -n "$at" ]; then
        read -r h m <<<"$hm"
        [ "$(printf '%02d:%02d' "$h" "$m")" = "$at" ] ||
          echo "  <- BACKUP_TIME is $want but the installed job runs at $at: run make backup-schedule"
      fi
      case "$last" in 0 | "" | "(never exited)") ;; *) echo "  <- THE LAST SCHEDULED BACKUP FAILED: see the log below" ;; esac
    else
      echo "Schedule: not installed (make backup-schedule)"
    fi
    [ -f "$LOG" ] && { echo "Last log lines ($LOG):"; tail -5 "$LOG" | sed 's/^/  /'; }
    # #356/#357/#383: macOS privacy controls can block the job (/bin/bash under launchd) from a
    # protected folder (iCloud Drive listing, personal folders) while the same command works in Terminal.
    if [ -f "$LOG" ] && tail -200 "$LOG" | grep -q "Operation not permitted\|can't write to"; then
      echo "  <- macOS blocked the scheduled job from a folder (Operation not permitted). Run make backup-now in"
      echo "     Terminal to compare; don't grant /bin/bash Full Disk Access (docs/setup/backups.md, macOS privacy)."
    fi
    ;;
  run)
    launchctl kickstart -p "gui/$(id -u)/$LABEL" >/dev/null && echo "Started $LABEL; follow $LOG"
    ;;
  *) echo "usage: $0 install|uninstall|status|run|plist|time" >&2; exit 2 ;;
esac

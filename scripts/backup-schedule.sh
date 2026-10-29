#!/bin/bash
# Daily verified backup via launchd (issue #41):
#   backup-schedule.sh install     run `make db-backup && make backup-prune` daily at 03:00
#   backup-schedule.sh uninstall   remove the job
#   backup-schedule.sh status      is it installed, its last exit, the last log lines
#   backup-schedule.sh run         run it now, exactly as launchd does
# A Mac that is asleep at 03:00 runs the job when it wakes. If Docker isn't running the
# backup fails, and that failure is logged and shown by `make backup-status`.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
LABEL=com.capitalos.db-backup
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$REPO/backups/backup.log"
# launchd starts with a minimal PATH; Docker Desktop and Homebrew live here.
JOB_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

case "${1:-}" in
  install)
    mkdir -p "$(dirname "$PLIST")" "$REPO/backups"
    cat >"$PLIST" <<EOF
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
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed $LABEL: daily at 03:00, log $LOG"
    ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL"
    ;;
  status)
    if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
      echo "Schedule: installed (daily at 03:00), last exit $(launchctl print "gui/$(id -u)/$LABEL" | sed -n 's/^[[:space:]]*last exit code = //p' | head -1)"
    else
      echo "Schedule: not installed (make backup-schedule)"
    fi
    [ -f "$LOG" ] && { echo "Last log lines ($LOG):"; tail -5 "$LOG" | sed 's/^/  /'; }
    ;;
  run)
    launchctl kickstart -p "gui/$(id -u)/$LABEL" >/dev/null && echo "Started $LABEL; follow $LOG"
    ;;
  *) echo "usage: $0 install|uninstall|status|run" >&2; exit 2 ;;
esac

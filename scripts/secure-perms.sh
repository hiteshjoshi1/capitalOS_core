#!/bin/bash
# File permissions for secrets and raw data (#442, review #431 R2). The Mac is single-user, but
# `.env` (Google client secret, DB password, API keys) and data/ (every raw statement) were
# readable by any account on it.
#   secure-perms.sh check   list anything wider than wanted; exit 1 if so (make status, deploy)
#   secure-perms.sh apply   fix it; DRY_RUN=1 only lists (make secure-perms / APPLY=1)
# Wanted: files 600, folders 700 (owner only). Docker Desktop shares bind mounts as the Mac
# user, so the API container (uid 10001) still reads and writes data/ and state/ (checked).
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mode=${1:-check}
# shellcheck source=backup-env.sh
. "$ROOT/scripts/backup-env.sh" 2>/dev/null && backup_env "$ROOT" 2>/dev/null || true

# "<wanted octal> <path>" for each existing path.
targets() {
  local p
  for p in "$ROOT/.env"; do [ -f "$p" ] && echo "600 $p"; done
  for p in "$ROOT/data" "$ROOT/state" "$ROOT/backups" "$HOME/.capitalos" "$HOME/.capitalos/backup"; do
    [ -d "$p" ] && echo "700 $p"
  done
  [ -f "$HOME/.capitalos/backup/age-identity.txt" ] && echo "600 $HOME/.capitalos/backup/age-identity.txt"
  # The backup folder (iCloud Drive): encrypted sets, but no reason for others to list them.
  if [ -n "${BACKUP_DIR:-}" ] && [ -d "$BACKUP_DIR" ] && [ "$BACKUP_DIR" != "$ROOT/backups" ]; then echo "700 $BACKUP_DIR"; fi
}

mode_of() { stat -f %Lp "$1" 2>/dev/null || stat -c %a "$1"; }

# Wider than wanted = any bit set that the wanted mode doesn't have (group/other access).
too_wide() {  # <have> <want>
  [ $(( 8#$1 & ~8#$2 & 8#777 )) -ne 0 ]
}

drift=0
while read -r want path; do
  [ -n "$path" ] || continue
  have=$(mode_of "$path")
  if too_wide "$have" "$want"; then
    drift=1
    case "$mode" in
      check) echo "WARNING: $path is $have (wanted $want): run make secure-perms APPLY=1" ;;
      apply)
        if [ -n "${DRY_RUN:-}" ]; then echo "would chmod $want $path (now $have)"
        else chmod "$want" "$path" && echo "chmod $want $path (was $have)"; fi ;;
    esac
  fi
done < <(targets)

case "$mode" in
  check) exit "$drift" ;;
  apply) [ "$drift" = 0 ] && echo "Permissions already tight: .env 600, data/state/backups and ~/.capitalos 700." ; exit 0 ;;
  *) echo "usage: $0 check|apply" >&2; exit 2 ;;
esac

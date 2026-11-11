# Where backups live and how they're encrypted (#356). Sourced (bash) by db-backup.sh,
# deploy.sh, status.sh and test-instance.sh, so they all agree. Call: backup_env <repo dir>.
#
# Each setting comes from the environment first, then the repo's .env, then a default:
#   BACKUP_DIR            where backup sets go. From .env only in the MAIN checkout: a worktree
#                         or the test instance (which links the main .env) keeps its own
#                         <repo>/backups, so a copy never writes into the real backup folder.
#   BACKUP_AGE_RECIPIENT  age public key (age1...). Set: every new set is encrypted to it.
#                         Unset: plain sets, as before #356 (worktrees, CI, fresh clones).
#   BACKUP_AGE_IDENTITY   the private key file that decrypts; default
#                         ~/.capitalos/backup/age-identity.txt (outside the repo).
#   BACKUP_OFFSITE_DIR    a second folder (iCloud Drive) that gets a copy of every encrypted set
#                         (#357). Like BACKUP_DIR, from .env only in the main checkout; unset: none.
#   BACKUP_TIME           when the daily scheduled backup runs, HH:MM (24-hour, local time);
#                         default 13:00 (#387: the Mac is usually asleep at night). Read by
#                         scripts/backup-schedule.sh (backup_time); takes effect on `make backup-schedule`.
# shellcheck shell=bash

backup_env_value() {  # <.env file> <name>: the last NAME=value line, quotes stripped
  [ -f "$1" ] || return 0
  sed -n "s/^$2=//p" "$1" | tail -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

backup_is_main_checkout() {  # <repo dir>
  local g c
  # Physical paths (pwd -P): /var vs /private/var on macOS would otherwise differ.
  g=$(cd "$1" && cd "$(git rev-parse --absolute-git-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 1
  c=$(cd "$1" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 1
  [ "$g" = "$c" ]
}

BACKUP_TIME_DEFAULT=13:00

# "H M" (no leading zeros) for a 24-hour HH:MM (or H:MM) time; fails on anything else (#387).
backup_time_parse() {  # <HH:MM>
  local h m
  [[ "$1" =~ ^([0-9]{1,2}):([0-9]{2})$ ]] || return 1
  h=$((10#${BASH_REMATCH[1]})) m=$((10#${BASH_REMATCH[2]}))
  [ "$h" -le 23 ] && [ "$m" -le 59 ] || return 1
  echo "$h $m"
}

# The configured daily backup time (HH:MM): the environment, then the repo's .env, then 13:00.
backup_time() {  # <repo dir>
  local t=${BACKUP_TIME:-}
  [ -n "$t" ] || t=$(backup_env_value "$1/.env" BACKUP_TIME)
  echo "${t:-$BACKUP_TIME_DEFAULT}"
}

backup_env() {  # <repo dir>
  local repo=$1 env="$1/.env" v
  if [ -z "${BACKUP_DIR:-}" ]; then
    v=""
    backup_is_main_checkout "$repo" && v=$(backup_env_value "$env" BACKUP_DIR)
    BACKUP_DIR=${v:-$repo/backups}
  fi
  case "$BACKUP_DIR" in "~/"*) BACKUP_DIR="$HOME/${BACKUP_DIR#\~/}" ;; esac
  if [ -z "${BACKUP_OFFSITE_DIR+set}" ]; then
    BACKUP_OFFSITE_DIR=""
    backup_is_main_checkout "$repo" && BACKUP_OFFSITE_DIR=$(backup_env_value "$env" BACKUP_OFFSITE_DIR)
  fi
  case "$BACKUP_OFFSITE_DIR" in "~/"*) BACKUP_OFFSITE_DIR="$HOME/${BACKUP_OFFSITE_DIR#\~/}" ;; esac
  if [ -z "${BACKUP_AGE_RECIPIENT+set}" ]; then BACKUP_AGE_RECIPIENT=$(backup_env_value "$env" BACKUP_AGE_RECIPIENT); fi
  if [ -z "${BACKUP_AGE_IDENTITY:-}" ]; then BACKUP_AGE_IDENTITY=$(backup_env_value "$env" BACKUP_AGE_IDENTITY); fi
  BACKUP_AGE_IDENTITY=${BACKUP_AGE_IDENTITY:-$HOME/.capitalos/backup/age-identity.txt}
  case "$BACKUP_AGE_IDENTITY" in "~/"*) BACKUP_AGE_IDENTITY="$HOME/${BACKUP_AGE_IDENTITY#\~/}" ;; esac
  export BACKUP_DIR BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY BACKUP_OFFSITE_DIR
}

# Where a backup folder's index lives (#383). In iCloud Drive the daily job (launchd) could neither
# read nor replace an index file Terminal had written there ("Operation not permitted"), so an
# iCloud folder's index is kept on the Mac in ~/.capitalos/backup/index/ (no privacy controls
# there; it is only a list of names, rebuilt from a listing in Terminal if lost). BACKUP_INDEX_DIR
# overrides it for every folder; other folders keep it inside as .capitalos-index (worktrees, tests).
backup_index_of() {  # <dir>
  local key
  if [ -n "${BACKUP_INDEX_DIR:-}" ] || [[ "$1" == "$HOME/Library/Mobile Documents/"* ]]; then
    key=$(printf '%s' "$1" | sed 's#^/##; s#[^A-Za-z0-9._-]#_#g')
    printf '%s/%s.index' "${BACKUP_INDEX_DIR:-$HOME/.capitalos/backup/index}" "$key"
  else
    printf '%s/.capitalos-index' "$1"
  fi
}

# The newest verified set's logical path (capitalos_<ts>.dump, whether stored plain or as .age).
# #383: from a listing, else from the folder's index (.capitalos-index, or the pre-#383
# .capitalos-offsite-index): under launchd macOS refuses listing an iCloud Drive folder. Names
# carry the timestamp, so the last name in order is the newest.
backup_newest_verified() {
  local idx n
  if [ "${BACKUP_TEST_UNLISTABLE:-}" != all ] && [ "${BACKUP_TEST_UNLISTABLE:-}" != local ] && ls -1 "$BACKUP_DIR" >/dev/null 2>&1; then
    n=$(ls -1 "$BACKUP_DIR" 2>/dev/null | sed -n 's/^\(capitalos_.*\.dump\)\.verified$/\1/p' | sort | tail -1)
  else
    idx=$(backup_index_of "$BACKUP_DIR")
    [ -f "$idx" ] || idx="$BACKUP_DIR/.capitalos-index"
    [ -f "$idx" ] || idx="$BACKUP_DIR/.capitalos-offsite-index"
    [ -f "$idx" ] && [ -r "$idx" ] || return 0
    n=$( { while IFS= read -r n; do [ -n "$n" ] && [ -e "$BACKUP_DIR/$n.verified" ] && echo "$n"; done <"$idx"; } 2>/dev/null | sort | tail -1)
  fi
  [ -n "$n" ] && printf '%s/%s\n' "$BACKUP_DIR" "$n"
  return 0
}

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

backup_env() {  # <repo dir>
  local repo=$1 env="$1/.env" v
  if [ -z "${BACKUP_DIR:-}" ]; then
    v=""
    backup_is_main_checkout "$repo" && v=$(backup_env_value "$env" BACKUP_DIR)
    BACKUP_DIR=${v:-$repo/backups}
  fi
  case "$BACKUP_DIR" in "~/"*) BACKUP_DIR="$HOME/${BACKUP_DIR#\~/}" ;; esac
  if [ -z "${BACKUP_AGE_RECIPIENT+set}" ]; then BACKUP_AGE_RECIPIENT=$(backup_env_value "$env" BACKUP_AGE_RECIPIENT); fi
  if [ -z "${BACKUP_AGE_IDENTITY:-}" ]; then BACKUP_AGE_IDENTITY=$(backup_env_value "$env" BACKUP_AGE_IDENTITY); fi
  BACKUP_AGE_IDENTITY=${BACKUP_AGE_IDENTITY:-$HOME/.capitalos/backup/age-identity.txt}
  case "$BACKUP_AGE_IDENTITY" in "~/"*) BACKUP_AGE_IDENTITY="$HOME/${BACKUP_AGE_IDENTITY#\~/}" ;; esac
  export BACKUP_DIR BACKUP_AGE_RECIPIENT BACKUP_AGE_IDENTITY
}

# The newest verified set's logical path (capitalos_<ts>.dump, whether stored plain or as .age).
backup_newest_verified() {
  ls -1t "$BACKUP_DIR"/capitalos_*.dump.verified 2>/dev/null | head -1 | sed 's/\.verified$//'
}

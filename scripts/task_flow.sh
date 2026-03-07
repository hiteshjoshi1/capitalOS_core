#!/usr/bin/env bash
set -euo pipefail

MAX_RETRIES="${MAX_RETRIES:-3}"
PLAN_MODEL="${PLAN_MODEL:-claude-opus-4.6}"
REVIEW_MODEL="${REVIEW_MODEL:-claude-sonnet-4.6}"
REVIEW_ESCALATION_MODEL="${REVIEW_ESCALATION_MODEL:-claude-opus-4.6}"
CODEX_TIMEOUT_MINUTES="${CODEX_TIMEOUT_MINUTES:-60}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TASK_TEMPLATE="$REPO_ROOT/tasks/_template.md"

cd "$REPO_ROOT"

TASK_FILE=""
TASK_BASENAME=""
ISSUE_ID=""
SLUG=""
BRANCH=""

usage() {
  cat <<'EOF'
Usage:
  scripts/task_flow.sh plan  tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh build tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh review tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh ship  tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh all   tasks/issue-<id>-<slug>.md

Environment overrides:
  PLAN_MODEL=claude-opus-4.6
  REVIEW_MODEL=claude-sonnet-4.6
  REVIEW_ESCALATION_MODEL=claude-opus-4.6
  MAX_RETRIES=3
  CODEX_TIMEOUT_MINUTES=60
EOF
}

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
  printf '[%s] %s\n' "$(timestamp)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

require_tool() {
  local tool="$1"
  command -v "$tool" >/dev/null 2>&1 || die "Required tool not found: $tool"
}

validate_task_file() {
  TASK_FILE="$1"
  TASK_BASENAME="$(basename "$TASK_FILE")"

  if [[ ! "$TASK_FILE" =~ ^tasks/ ]]; then
    die "Task file must be under tasks/: $TASK_FILE"
  fi
  if [[ ! "$TASK_BASENAME" =~ ^issue-([0-9]+)-([a-z0-9][a-z0-9-]*)\.md$ ]]; then
    die "Task filename must match issue-<id>-<slug>.md"
  fi

  ISSUE_ID="${BASH_REMATCH[1]}"
  SLUG="${BASH_REMATCH[2]}"
  BRANCH="feature/issue-${ISSUE_ID}-${SLUG}"
}

task_title_from_slug() {
  echo "$SLUG" | tr '-' ' ' | sed 's/\b\(.\)/\u\1/g'
}

ensure_task_file_exists() {
  if [[ -f "$TASK_FILE" ]]; then
    return
  fi

  [[ -f "$TASK_TEMPLATE" ]] || die "Task template not found: $TASK_TEMPLATE"
  mkdir -p "$(dirname "$TASK_FILE")"

  local title
  title="$(task_title_from_slug)"
  sed \
    -e "s/<id>/${ISSUE_ID}/g" \
    -e "s/<title>/${title}/g" \
    "$TASK_TEMPLATE" > "$TASK_FILE"

  log "Created task file from template: $TASK_FILE"
}

append_task_block() {
  local title="$1"
  local body="$2"
  if [[ -z "$TASK_FILE" || ! -f "$TASK_FILE" ]]; then
    log "$title: $body"
    return 0
  fi
  {
    echo
    echo "### ${title} ($(timestamp))"
    echo
    echo '```text'
    printf '%s\n' "$body"
    echo '```'
  } >> "$TASK_FILE"
}

append_retry_log() {
  local body="$1"
  append_task_block "Retry Entry" "$body"
}

immutable_hash() {
  grep -q "<!-- IMMUTABLE_PLAN_END -->" "$TASK_FILE" || die "Missing IMMUTABLE_PLAN_END marker in $TASK_FILE"
  awk '
    { print }
    /<!-- IMMUTABLE_PLAN_END -->/ { exit }
  ' "$TASK_FILE" | shasum -a 256 | awk '{print $1}'
}

is_human_approved() {
  grep -Eiq '^- \[[xX]\] Approved for implementation' "$TASK_FILE"
}

assert_clean_worktree() {
  if ! git diff --quiet || ! git diff --cached --quiet; then
    die "Working tree is dirty. Commit/stash changes before running workflow commands."
  fi
}

run_with_retries() {
  local label="$1"
  shift
  local attempt rc

  for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
    log "$label (attempt $attempt/$MAX_RETRIES)"
    if "$@"; then
      return 0
    fi
    rc=$?
    append_retry_log "$label failed on attempt $attempt with exit code $rc: $*"
  done

  append_retry_log "$label failed after $MAX_RETRIES attempts."
  return 1
}

prepare_branch_from_main() {
  run_with_retries "Checkout main" git checkout main
  run_with_retries "Pull latest main" git pull --rebase
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    run_with_retries "Checkout existing branch $BRANCH" git checkout "$BRANCH"
  else
    run_with_retries "Create branch $BRANCH" git checkout -b "$BRANCH"
  fi
}

commit_and_push_task_file() {
  local message="$1"
  git add "$TASK_FILE"
  if git diff --cached --quiet; then
    log "No task-file changes to commit."
    return 0
  fi
  git commit -m "$message"
  run_with_retries "Push branch $BRANCH" git push -u origin "$BRANCH"
}

run_copilot_prompt() {
  local model="$1"
  local prompt="$2"
  copilot --model "$model" -p "$prompt" -s --no-color --stream off
}

run_codex_prompt() {
  local prompt="$1"
  if command -v timeout >/dev/null 2>&1; then
    timeout "${CODEX_TIMEOUT_MINUTES}m" codex exec --full-auto --sandbox workspace-write "$prompt"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    gtimeout "${CODEX_TIMEOUT_MINUTES}m" codex exec --full-auto --sandbox workspace-write "$prompt"
    return
  fi
  codex exec --full-auto --sandbox workspace-write "$prompt"
}

run_verification_suite() {
  run_with_retries "make lint" make lint
  run_with_retries "make typecheck" make typecheck
  run_with_retries "make test-backend" make test-backend
  run_with_retries "make test-frontend" make test-frontend
  if [[ -f "$REPO_ROOT/web/playwright.config.ts" || -f "$REPO_ROOT/web/playwright.config.js" ]]; then
    run_with_retries "make e2e" make e2e
  else
    append_task_block "Verification Note" "Playwright not configured; skipped make e2e."
  fi
}

parse_status() {
  local output="$1"
  echo "$output" | awk -F':' '/^STATUS:/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print toupper($2); exit}'
}

parse_risk() {
  local output="$1"
  echo "$output" | awk -F':' '/^RISK:/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print toupper($2); exit}'
}

review_needs_escalation() {
  local status="$1"
  local risk="$2"
  local output="$3"
  if [[ "$status" == "ESCALATE" || "$risk" == "HIGH" ]]; then
    return 0
  fi
  if echo "$output" | grep -Eiq 'uncertain|conflict|high-risk|cannot conclude|inconclusive'; then
    return 0
  fi
  return 1
}

cmd_plan() {
  require_tool git
  require_tool copilot
  validate_task_file "$1"
  assert_clean_worktree
  prepare_branch_from_main
  ensure_task_file_exists

  local prompt output
  prompt="$(cat <<EOF
You are planning work for CapitalOS.
Model role: architecture/planning.
Task file: $TASK_FILE

Return concise markdown with:
1) Architecture decisions (deterministic)
2) Risks
3) Open questions (only if critical)
4) Task breakdown aligned to acceptance criteria

Do not write any code. Do not suggest scope expansion.

Current task file content:
$(cat "$TASK_FILE")
EOF
)"
  output="$(run_copilot_prompt "$PLAN_MODEL" "$prompt")"
  append_task_block "Planning Output (${PLAN_MODEL})" "$output"
  append_task_block "Human Gate Reminder" "Review the plan and set '- [x] Approved for implementation' before build."
  commit_and_push_task_file "plan: issue #${ISSUE_ID} with ${PLAN_MODEL}"
  log "Plan complete. Human approval gate must be checked before build."
}

cmd_build() {
  require_tool codex
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"
  is_human_approved || die "Human gate not approved. Check '- [x] Approved for implementation' in $TASK_FILE."

  local immutable_before immutable_after prompt
  immutable_before="$(immutable_hash)"

  prompt="$(cat <<EOF
Implement the approved task defined in $TASK_FILE.

Hard constraints:
1) Do not change any content above the marker <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
2) You may update only mutable parts of $TASK_FILE:
   - Task Checklist
   - Implementation Reasoning Addendum
   - Verification Evidence
   - Retry Log
   - Automation Log
3) Keep changes in-scope for the task acceptance criteria.
4) Run required checks:
   - make lint
   - make typecheck
   - make test-backend
   - make test-frontend
   - make e2e only if Playwright exists
5) If a command fails, fix and retry up to ${MAX_RETRIES} times per failing command.
EOF
)"

  run_with_retries "Codex implementation pass" run_codex_prompt "$prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed by implementation pass."
    die "Immutable approved plan content changed in $TASK_FILE."
  fi

  run_verification_suite
  append_task_block "Build Result" "Implementation and verification suite completed successfully."
}

run_sonnet_review() {
  local diff_stat diff_names prompt
  diff_stat="$(git diff --no-color --stat main...HEAD || true)"
  diff_names="$(git diff --name-only main...HEAD || true)"
  prompt="$(cat <<EOF
You are a strict reviewer for CapitalOS.
Primary review model.

Task file:
$(cat "$TASK_FILE")

Changed files:
$diff_names

Diff summary:
$diff_stat

Return EXACTLY:
STATUS: APPROVED|NEEDS_FIXES|ESCALATE
RISK: LOW|MEDIUM|HIGH
SUMMARY:
- ...
FINDINGS:
- ...
TEST_GAPS:
- ...

Use STATUS=ESCALATE when uncertain, conflicting, or high-risk.
EOF
)"
  run_copilot_prompt "$REVIEW_MODEL" "$prompt"
}

run_opus_escalation_review() {
  local sonnet_output="$1"
  local prompt
  prompt="$(cat <<EOF
You are the escalation reviewer for CapitalOS.
Primary review from Sonnet is below.

Sonnet review:
$sonnet_output

Task file:
$(cat "$TASK_FILE")

Return EXACTLY:
STATUS: APPROVED|NEEDS_FIXES
RISK: LOW|MEDIUM|HIGH
SUMMARY:
- ...
FINDINGS:
- ...
TEST_GAPS:
- ...
EOF
)"
  run_copilot_prompt "$REVIEW_ESCALATION_MODEL" "$prompt"
}

cmd_review() {
  require_tool copilot
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

  local sonnet_output sonnet_status sonnet_risk
  sonnet_output="$(run_sonnet_review)"
  sonnet_status="$(parse_status "$sonnet_output")"
  sonnet_risk="$(parse_risk "$sonnet_output")"

  append_task_block "Sonnet Review (${REVIEW_MODEL})" "$sonnet_output"

  if review_needs_escalation "$sonnet_status" "$sonnet_risk" "$sonnet_output"; then
    local opus_output opus_status
    opus_output="$(run_opus_escalation_review "$sonnet_output")"
    opus_status="$(parse_status "$opus_output")"
    append_task_block "Opus Escalation Review (${REVIEW_ESCALATION_MODEL})" "$opus_output"
    if [[ "$opus_status" == "APPROVED" ]]; then
      return 0
    fi
    return 2
  fi

  if [[ "$sonnet_status" == "APPROVED" ]]; then
    return 0
  fi
  return 2
}

run_codex_rework() {
  local immutable_before immutable_after prompt
  immutable_before="$(immutable_hash)"
  prompt="$(cat <<EOF
Rework the current branch implementation for $TASK_FILE based on the latest review findings.

Rules:
1) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
2) Fix only findings relevant to acceptance criteria and failing checks.
3) Update mutable task sections with concise reasoning and verification evidence.
4) Keep changes minimal and in-scope.
EOF
)"
  run_with_retries "Codex rework pass" run_codex_prompt "$prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed during rework."
    die "Immutable approved plan content changed during rework."
  fi
}

cmd_ship() {
  require_tool git
  require_tool gh
  validate_task_file "$1"

  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$current_branch" != "main" ]] || die "Refusing to ship from main branch."

  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "feat: complete issue #${ISSUE_ID} workflow execution"
  else
    log "No staged changes to commit before ship."
  fi
  run_with_retries "Push branch $BRANCH" git push -u origin "$BRANCH"

  if gh pr view --head "$BRANCH" --json number >/dev/null 2>&1; then
    log "PR already exists for $BRANCH."
  else
    gh pr create \
      --base main \
      --head "$BRANCH" \
      --title "Issue #${ISSUE_ID}: ${SLUG}" \
      --body "Automated by task_flow.sh with Opus plan, Codex implementation, Sonnet review, and Opus escalation-on-risk."
    log "PR created for $BRANCH -> main."
  fi
}

cmd_all() {
  local task="$1"
  cmd_plan "$task"
  if ! is_human_approved; then
    log "Human gate pending. Review $TASK_FILE, check approval, then rerun:"
    log "scripts/task_flow.sh all $TASK_FILE"
    return 0
  fi

  cmd_build "$task"

  local review_attempt rc
  for ((review_attempt=1; review_attempt<=MAX_RETRIES; review_attempt++)); do
    log "Review cycle attempt $review_attempt/$MAX_RETRIES"
    if cmd_review "$task"; then
      append_task_block "Review Result" "Review approved on attempt $review_attempt."
      cmd_ship "$task"
      return 0
    fi
    rc=$?
    if [[ "$rc" -ne 2 ]]; then
      die "Unexpected review failure code: $rc"
    fi
    append_retry_log "Review requested rework on attempt $review_attempt."
    if (( review_attempt == MAX_RETRIES )); then
      die "Reached max review/rework attempts ($MAX_RETRIES)."
    fi
    run_codex_rework
    run_verification_suite
  done
}

main() {
  [[ $# -eq 2 ]] || { usage; exit 1; }
  local cmd="$1"
  local task="$2"

  case "$cmd" in
    plan) cmd_plan "$task" ;;
    build) cmd_build "$task" ;;
    review) cmd_review "$task" ;;
    ship) cmd_ship "$task" ;;
    all) cmd_all "$task" ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"

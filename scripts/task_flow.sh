#!/usr/bin/env bash
set -euo pipefail

MAX_RETRIES="${MAX_RETRIES:-3}"
PLAN_MODEL="${PLAN_MODEL:-claude-opus-4.6}"
REVIEW_MODEL="${REVIEW_MODEL:-claude-sonnet-4.6}"
REVIEW_ESCALATION_MODEL="${REVIEW_ESCALATION_MODEL:-claude-opus-4.6}"
CODEX_TIMEOUT_MINUTES="${CODEX_TIMEOUT_MINUTES:-60}"
ENABLE_CAFFEINATE="${ENABLE_CAFFEINATE:-1}"
COPILOT_TOOL_MODE="${COPILOT_TOOL_MODE:-text-only}"

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
  scripts/task_flow.sh rework tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh ship  tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh all   tasks/issue-<id>-<slug>.md

Environment overrides:
  PLAN_MODEL=claude-opus-4.6
  REVIEW_MODEL=claude-sonnet-4.6
  REVIEW_ESCALATION_MODEL=claude-opus-4.6
  MAX_RETRIES=3
  CODEX_TIMEOUT_MINUTES=60
  ENABLE_CAFFEINATE=1
  COPILOT_TOOL_MODE=text-only
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

run_with_caffeinate_for_codex() {
  if [[ "$ENABLE_CAFFEINATE" == "1" ]] && command -v caffeinate >/dev/null 2>&1; then
    caffeinate -dimsu "$@"
    return
  fi
  "$@"
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

assert_task_path_writable() {
  local task_dir
  task_dir="$(dirname "$TASK_FILE")"

  [[ -d "$task_dir" ]] || die "Task directory does not exist: $task_dir"
  [[ -w "$task_dir" ]] || die "Task directory is not writable: $task_dir"

  if [[ -f "$TASK_FILE" ]]; then
    [[ -w "$TASK_FILE" ]] || die "Task file is not writable: $TASK_FILE"
  fi
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

next_review_id() {
  local max_id
  max_id="$(grep -Eo '^### Review Cycle R[0-9]+' "$TASK_FILE" 2>/dev/null | sed -E 's/^### Review Cycle R([0-9]+).*$/\1/' | sort -n | tail -n1)"
  if [[ -z "$max_id" ]]; then
    echo "R1"
  else
    echo "R$((max_id + 1))"
  fi
}

latest_review_id() {
  local latest
  latest="$(grep -Eo '^### Review Cycle R[0-9]+' "$TASK_FILE" 2>/dev/null | sed -E 's/^### Review Cycle (R[0-9]+).*$/\1/' | tail -n1)"
  [[ -n "$latest" ]] || return 1
  echo "$latest"
}

append_review_status() {
  local review_id="$1"
  local status="$2"
  local result="$3"
  local risk="$4"
  append_task_block "Review Cycle ${review_id} - Status" "Review-ID: ${review_id}
Status: ${status}
Result: ${result}
Risk: ${risk}"
}

review_status_exists() {
  local review_id="$1"
  local expected_status="$2"
  awk -v rid="Review-ID: ${review_id}" -v st="Status: ${expected_status}" '
    $0 == rid {in_block=1; next}
    in_block && /^Status:/ { if ($0 == st) found=1; in_block=0 }
    END { exit found ? 0 : 1 }
  ' "$TASK_FILE"
}

extract_review_cycle_context() {
  local review_id="$1"
  awk -v rid="$review_id" '
    /^### Review Cycle / {
      if (capture && $0 !~ ("^### Review Cycle " rid " -")) exit
    }
    $0 ~ ("^### Review Cycle " rid " -") { capture=1 }
    capture { print }
  ' "$TASK_FILE"
}

extract_latest_legacy_review_context() {
  local start_line
  start_line="$(awk '/^### Sonnet Review / {line=NR} END {print line+0}' "$TASK_FILE")"
  if [[ "$start_line" -le 0 ]]; then
    return 1
  fi
  sed -n "${start_line},\$p" "$TASK_FILE"
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

has_unstaged_or_untracked_changes() {
  [[ -n "$(git diff --name-only)" || -n "$(git ls-files --others --exclude-standard)" ]]
}

assert_review_inputs_staged() {
  if ! has_unstaged_or_untracked_changes; then
    return 0
  fi
  local unstaged untracked
  unstaged="$(git diff --name-only)"
  untracked="$(git ls-files --others --exclude-standard)"
  log "Review requires a complete staged snapshot so reviewer sees all changes."
  if [[ -n "$unstaged" ]]; then
    log "Unstaged files:"
    printf '%s\n' "$unstaged" | sed 's/^/  - /'
  fi
  if [[ -n "$untracked" ]]; then
    log "Untracked files:"
    printf '%s\n' "$untracked" | sed 's/^/  - /'
  fi
  die "Stage changes before review (example: git add -A), then rerun task-review."
}

run_with_retries() {
  local label="$1"
  shift
  local attempt rc

  for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
    log "$label (attempt $attempt/$MAX_RETRIES)"
    set +e
    "$@"
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      return 0
    fi
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
  local args=(
    copilot
    --model "$model"
    -p "$prompt"
    --no-color
  )

  if [[ "$COPILOT_TOOL_MODE" == "text-only" ]]; then
    # Keep planning/review deterministic and avoid Copilot CLI tool permission failures.
    args+=(
      --no-ask-user
      --disable-builtin-mcps
      --deny-tool write
      --deny-tool shell
      --deny-tool url
    )
  fi

  "${args[@]}"
}

run_copilot_prompt_visible() {
  local model="$1"
  local prompt="$2"
  run_copilot_prompt "$model" "$prompt" 2>&1 | tee /dev/stderr
}

latest_copilot_session_plan() {
  local session_root="$HOME/.copilot/session-state"
  [[ -d "$session_root" ]] || return 1
  find "$session_root" -type f -name plan.md -exec stat -f '%m %N' {} \; 2>/dev/null \
    | sort -nr \
    | head -n 1 \
    | cut -d' ' -f2-
}

extract_between_task_markers() {
  local text="$1"
  printf '%s\n' "$text" | awk '
    /^[[:space:]]*<<<TASK_FILE_START>>>[[:space:]]*$/ { capture=1; next }
    /^[[:space:]]*<<<TASK_FILE_END>>>[[:space:]]*$/ { capture=0; found=1; exit }
    capture { print }
    END { if (!found) exit 1 }
  '
}

extract_task_file_from_fenced_block() {
  local text="$1"
  printf '%s\n' "$text" | awk '
    BEGIN { in_fence=0; found=0; block="" }
    /^[[:space:]]*```/ {
      if (!in_fence) {
        in_fence=1
        block=""
        next
      }
      in_fence=0
      if (index(block, "<!-- IMMUTABLE_PLAN_END -->") > 0 && index(block, "# Issue ") > 0) {
        printf "%s", block
        found=1
        exit
      }
      block=""
      next
    }
    in_fence { block = block $0 ORS }
    END { if (!found) exit 1 }
  '
}

resolve_plan_task_file_output() {
  local raw_output="$1"
  local extracted plan_file session_plan

  extracted="$(extract_between_task_markers "$raw_output" 2>/dev/null || true)"
  if [[ -n "$extracted" ]]; then
    echo "$extracted"
    return 0
  fi

  extracted="$(extract_task_file_from_fenced_block "$raw_output" 2>/dev/null || true)"
  if [[ -n "$extracted" ]]; then
    echo "$extracted"
    return 0
  fi

  if echo "$raw_output" | grep -qi "plan written to session plan.md"; then
    plan_file="$(latest_copilot_session_plan || true)"
    if [[ -n "$plan_file" && -s "$plan_file" ]]; then
      session_plan="$(cat "$plan_file")"
      extracted="$(extract_between_task_markers "$session_plan" 2>/dev/null || true)"
      if [[ -n "$extracted" ]]; then
        echo "$extracted"
        return 0
      fi
      extracted="$(extract_task_file_from_fenced_block "$session_plan" 2>/dev/null || true)"
      if [[ -n "$extracted" ]]; then
        echo "$extracted"
        return 0
      fi
      if grep -q "<!-- IMMUTABLE_PLAN_END -->" <<<"$session_plan" && grep -q "^# Issue " <<<"$session_plan"; then
        echo "$session_plan"
        return 0
      fi
    fi
  fi

  return 1
}

validate_generated_task_file_content() {
  local content="$1"
  grep -Eq '^# Issue [0-9]+:' <<<"$content" || return 1
  grep -q '^## Objective' <<<"$content" || return 1
  grep -q '^## Architecture Decisions' <<<"$content" || return 1
  grep -q '^## Acceptance Criteria' <<<"$content" || return 1
  grep -q '^## Human Approval Gate' <<<"$content" || return 1
  grep -q '^## Task Checklist' <<<"$content" || return 1
  grep -q '<!-- IMMUTABLE_PLAN_END -->' <<<"$content" || return 1
}

ensure_workflow_commands_in_task_file() {
  local content="$1"
  if grep -q '^## Workflow Commands' <<<"$content"; then
    echo "$content"
    return 0
  fi
  cat <<EOF
$content

## Workflow Commands

\`\`\`bash
make task-plan TASK=$TASK_FILE
make task-build TASK=$TASK_FILE
make task-review TASK=$TASK_FILE
make task-rework TASK=$TASK_FILE
make task-ship TASK=$TASK_FILE
\`\`\`
EOF
}

run_codex_prompt() {
  local prompt="$1"
  if command -v timeout >/dev/null 2>&1; then
    run_with_caffeinate_for_codex timeout "${CODEX_TIMEOUT_MINUTES}m" codex exec --full-auto --sandbox workspace-write "$prompt"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    run_with_caffeinate_for_codex gtimeout "${CODEX_TIMEOUT_MINUTES}m" codex exec --full-auto --sandbox workspace-write "$prompt"
    return
  fi
  run_with_caffeinate_for_codex codex exec --full-auto --sandbox workspace-write "$prompt"
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

collect_review_diff_names() {
  {
    git diff --name-only main...HEAD || true
    git diff --cached --name-only || true
    git diff --name-only || true
  } | awk 'NF' | sort -u
}

collect_review_diff_stat() {
  {
    git diff --no-color --stat main...HEAD || true
    git diff --cached --no-color --stat || true
    git diff --no-color --stat || true
  } | awk 'NF'
}

collect_review_diff_patch() {
  {
    echo "### COMMITTED_DIFF (main...HEAD)"
    git diff --no-color main...HEAD || true
    echo
    echo "### STAGED_UNCOMMITTED_DIFF"
    git diff --cached --no-color || true
    echo
    echo "### UNSTAGED_UNCOMMITTED_DIFF"
    git diff --no-color || true
  } | sed -n '1,4000p'
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
  assert_task_path_writable

  local prompt
  prompt="$(cat <<EOF
You are planning work for CapitalOS.
Model role: architecture/planning.
Task file: $TASK_FILE

Return ONLY the final task markdown between these exact markers:
<<<TASK_FILE_START>>>
...full task file markdown...
<<<TASK_FILE_END>>>

Requirements:
1) Provide a complete task file document (not partial notes) with sections:
   - Objective
   - Architecture Decisions
   - Risks
   - Open Questions
   - Acceptance Criteria
   - Human Approval Gate
   - Task Checklist
   - Workflow Commands (exact commands with TASK=$TASK_FILE)
   - Implementation Reasoning Addendum (Codex Mutable)
   - Verification Evidence (Codex Mutable)
   - Review Findings (Sonnet Primary, Opus Escalation)
   - Retry Log (Max 3)
   - Automation Log (Mutable)
2) Keep marker exactly: <!-- IMMUTABLE_PLAN_END -->
3) Keep output deterministic and scoped to requested feature.
4) Do not edit files directly; only return final markdown content between markers.
5) Do not include tool logs or transcripts inside the marked output.

Current task file content:
$(cat "$TASK_FILE")
EOF
)"
  local raw_output planned_task
  raw_output="$(run_copilot_prompt_visible "$PLAN_MODEL" "$prompt")"
  planned_task="$(resolve_plan_task_file_output "$raw_output" || true)"
  [[ -n "$planned_task" ]] || die "Planner output did not include a valid task document. No task file changes were written."

  planned_task="$(ensure_workflow_commands_in_task_file "$planned_task")"
  validate_generated_task_file_content "$planned_task" || die "Planner output failed required task-file structure checks."

  printf '%s\n' "$planned_task" > "$TASK_FILE"
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
  git add -A
  log "Auto-staged build outputs for review."
}

run_sonnet_review() {
  local diff_stat diff_names diff_patch prompt
  diff_stat="$(collect_review_diff_stat)"
  diff_names="$(collect_review_diff_names)"
  diff_patch="$(collect_review_diff_patch)"
  prompt="$(cat <<EOF
You are a strict reviewer for CapitalOS.
Primary review model.

Critical constraint:
- Do NOT execute shell/file tools (no git, ls, glob, read/write calls).
- Use only the provided task file and diff context below.

Task file:
$(cat "$TASK_FILE")

Changed files:
$diff_names

Diff summary:
$diff_stat

Unified diff (truncated to first 4000 lines):
$diff_patch

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
  local diff_patch prompt
  diff_patch="$(collect_review_diff_patch)"
  prompt="$(cat <<EOF
You are the escalation reviewer for CapitalOS.
Primary review from Sonnet is below.

Critical constraint:
- Do NOT execute shell/file tools (no git, ls, glob, read/write calls).
- Use only the provided Sonnet output, task file, and diff context.

Sonnet review:
$sonnet_output

Task file:
$(cat "$TASK_FILE")

Unified diff (truncated to first 4000 lines):
$diff_patch

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
  assert_review_inputs_staged

  local review_id sonnet_output sonnet_status sonnet_risk
  review_id="$(next_review_id)"
  sonnet_output="$(run_sonnet_review 2>&1 | tee /dev/stderr)"
  sonnet_status="$(parse_status "$sonnet_output")"
  sonnet_risk="$(parse_risk "$sonnet_output")"

  append_task_block "Review Cycle ${review_id} - Sonnet (${REVIEW_MODEL})" "$sonnet_output"
  append_review_status "$review_id" "Reviewed" "$sonnet_status" "${sonnet_risk:-UNKNOWN}"

  if review_needs_escalation "$sonnet_status" "$sonnet_risk" "$sonnet_output"; then
    local opus_output opus_status
    opus_output="$(run_opus_escalation_review "$sonnet_output" 2>&1 | tee /dev/stderr)"
    opus_status="$(parse_status "$opus_output")"
    append_task_block "Review Cycle ${review_id} - Opus Escalation (${REVIEW_ESCALATION_MODEL})" "$opus_output"
    append_review_status "$review_id" "Reviewed" "$opus_status" "$(parse_risk "$opus_output")"
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

cmd_rework() {
  require_tool codex
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

  local review_id review_context latest_result immutable_before immutable_after prompt parsed_status parsed_risk
  review_id="$(latest_review_id || true)"
  if [[ -z "$review_id" ]]; then
    review_context="$(extract_latest_legacy_review_context || true)"
    [[ -n "$review_context" ]] || die "No review cycle found. Run task-review first."
    review_id="R0"
    parsed_status="$(parse_status "$review_context")"
    parsed_risk="$(parse_risk "$review_context")"
    append_review_status "$review_id" "Reviewed" "${parsed_status:-UNKNOWN}" "${parsed_risk:-UNKNOWN}"
  fi

  if review_status_exists "$review_id" "Implemented"; then
    die "Latest review cycle ($review_id) is already marked Implemented."
  fi
  if ! review_status_exists "$review_id" "Reviewed"; then
    die "Latest review cycle ($review_id) is not marked Reviewed."
  fi

  latest_result="$(awk -v rid="Review-ID: ${review_id}" '
    $0 == rid {in_block=1; next}
    in_block && /^Result:/ {sub(/^Result:[ \t]*/, "", $0); print toupper($0); exit}
    in_block && /^### / {in_block=0}
  ' "$TASK_FILE")"

  if [[ "$latest_result" == "APPROVED" ]]; then
    die "Latest review cycle ($review_id) is APPROVED. No rework needed."
  fi

  if [[ "$review_id" != "R0" ]]; then
    review_context="$(extract_review_cycle_context "$review_id")"
    [[ -n "$review_context" ]] || die "Could not extract review context for $review_id."
  fi

  immutable_before="$(immutable_hash)"
  prompt="$(cat <<EOF
Implement ONLY the unresolved issues from latest review cycle ${review_id} in $TASK_FILE.

Latest review context:
$review_context

Hard constraints:
1) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
2) Fix only findings and test gaps from the latest review cycle (${review_id}).
3) Do not redo completed work or broad refactors.
4) Keep changes minimal and in-scope with acceptance criteria.
5) Update mutable sections in $TASK_FILE with concise implementation reasoning and verification evidence.
6) Run verification:
   - make lint
   - make typecheck
   - make test-backend
   - make test-frontend
   - make e2e only if Playwright exists
EOF
)"

  run_with_retries "Codex rework pass (${review_id})" run_codex_prompt "$prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed during rework for ${review_id}."
    die "Immutable approved plan content changed during rework."
  fi

  run_verification_suite
  append_review_status "$review_id" "Implemented" "NEEDS_REVIEW" "PENDING"
  append_task_block "Review Cycle ${review_id} - Rework Result" "Targeted rework implemented for latest review findings."
  git add -A
  log "Auto-staged rework outputs for review."
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
    local pr_out pr_rc
    set +e
    pr_out="$(gh pr create \
      --base main \
      --head "$BRANCH" \
      --title "Issue #${ISSUE_ID}: ${SLUG}" \
      --body "Automated by task_flow.sh with Opus plan, Codex implementation, Sonnet review, and Opus escalation-on-risk." 2>&1)"
    pr_rc=$?
    set -e

    if [[ "$pr_rc" -eq 0 ]]; then
      log "PR created for $BRANCH -> main."
    elif echo "$pr_out" | grep -qi "already exists"; then
      log "PR already exists for $BRANCH."
    else
      echo "$pr_out" >&2
      die "Failed to create PR for $BRANCH."
    fi
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
    git add -A
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
    cmd_rework "$task"
  done
}

main() {
  [[ $# -eq 2 ]] || { usage; exit 1; }
  local cmd="$1"
  local task="$2"
  local rc

  case "$cmd" in
    plan) cmd_plan "$task" ;;
    build) cmd_build "$task" ;;
    review)
      set +e
      cmd_review "$task"
      rc=$?
      set -e
      if [[ "$rc" -eq 2 ]]; then
        log "Review returned NEEDS_FIXES/ESCALATE. Findings recorded in $TASK_FILE."
        exit 0
      fi
      exit "$rc"
      ;;
    rework) cmd_rework "$task" ;;
    ship) cmd_ship "$task" ;;
    all) cmd_all "$task" ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

MAX_RETRIES="${MAX_RETRIES-}"
PLAN_MODEL="${PLAN_MODEL-}"
REVIEW_MODEL="${REVIEW_MODEL-}"
REVIEW_ESCALATION_MODEL="${REVIEW_ESCALATION_MODEL-}"
CODEX_TIMEOUT_MINUTES="${CODEX_TIMEOUT_MINUTES-}"
ENABLE_CAFFEINATE="${ENABLE_CAFFEINATE-}"
COPILOT_TOOL_MODE="${COPILOT_TOOL_MODE-}"
CONTEXT7_ENABLED="${CONTEXT7_ENABLED-}"
COPILOT_MCP_CONFIG="${COPILOT_MCP_CONFIG-}"
NO_CACHE="${NO_CACHE-}"
VERBOSE=0
CONTEXT7_AVAILABLE_STATE=""
CONTEXT7_WARNING_EMITTED=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${TASK_FLOW_RUNTIME_ACTIVE:-0}" == "1" && -n "${TASK_FLOW_REPO_ROOT:-}" ]]; then
  REPO_ROOT="$TASK_FLOW_REPO_ROOT"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
TASK_TEMPLATE="$REPO_ROOT/tasks/_template.md"
MODEL_CONFIG_FILE="$REPO_ROOT/.ai-models.env"
CACHE_DIR="$REPO_ROOT/.task-cache"

cd "$REPO_ROOT"

TASK_FILE=""
TASK_BASENAME=""
ISSUE_ID=""
SLUG=""
BRANCH=""

usage() {
  cat <<'EOF'
Usage:
  scripts/task_flow.sh [--verbose] prepare tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] plan    tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] build   tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] review  tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] rework  tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] ship    tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] all     tasks/issue-<id>-<slug>.md

Environment overrides:
  PLAN_MODEL=<planner model>
  REVIEW_MODEL=<primary reviewer model>
  REVIEW_ESCALATION_MODEL=<escalation reviewer model>
  MAX_RETRIES=3
  CODEX_TIMEOUT_MINUTES=60
  ENABLE_CAFFEINATE=1
  COPILOT_TOOL_MODE=text-only
  CONTEXT7_ENABLED=0
  COPILOT_MCP_CONFIG=~/.copilot/mcp-config.json
  NO_CACHE=0
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

stage_requires_self_integrity() {
  local stage="$1"
  case "$stage" in
    plan|build|review|rework|all) return 0 ;;
    *) return 1 ;;
  esac
}

file_sha256() {
  local path="$1"
  shasum -a 256 "$path" | awk '{print $1}'
}

validate_pipeline_script_if_changed() {
  local before_hash="$1"
  local script_path="$REPO_ROOT/scripts/task_flow.sh"
  local after_hash

  after_hash="$(file_sha256 "$script_path")"
  if [[ "$before_hash" == "$after_hash" ]]; then
    return 0
  fi

  log "Detected script change during run; validating syntax: $script_path"
  if ! bash -n "$script_path"; then
    log "ERROR: Self-integrity check failed: invalid syntax in modified scripts/task_flow.sh"
    return 1
  fi

  log "Self-integrity check passed for modified scripts/task_flow.sh"
}

activate_runtime_self_integrity() {
  local source_script="$REPO_ROOT/scripts/task_flow.sh"
  local runtime_script before_hash rc

  runtime_script="$(mktemp "/tmp/task_flow.runtime.XXXXXX")"
  before_hash="$(file_sha256 "$source_script")"
  cp "$source_script" "$runtime_script"
  chmod 700 "$runtime_script"

  log "Self-integrity mode active; runtime script path: $runtime_script"

  set +e
  TASK_FLOW_RUNTIME_ACTIVE=1 \
  TASK_FLOW_REPO_ROOT="$REPO_ROOT" \
  bash "$runtime_script" "$@"
  rc=$?
  set -e

  rm -f "$runtime_script"

  if ! validate_pipeline_script_if_changed "$before_hash"; then
    die "Self-integrity check failed. Fix scripts/task_flow.sh syntax before rerunning."
  fi

  exit "$rc"
}

require_non_empty_config() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "Missing required config value: $name"
}

require_binary_flag_config() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[01]$ ]] || die "Config $name must be 0 or 1 (got: $value)"
}

require_positive_integer_config() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || die "Config $name must be a positive integer (got: $value)"
  (( value >= 1 )) || die "Config $name must be >= 1 (got: $value)"
}

print_model_routing_table() {
  log "Active model routing:"
  log "  PLAN_MODEL=$PLAN_MODEL"
  log "  REVIEW_MODEL=$REVIEW_MODEL"
  log "  REVIEW_ESCALATION_MODEL=$REVIEW_ESCALATION_MODEL"
  log "  CODEX_TIMEOUT_MINUTES=$CODEX_TIMEOUT_MINUTES"
  log "  MAX_RETRIES=$MAX_RETRIES"
  log "  COPILOT_TOOL_MODE=$COPILOT_TOOL_MODE"
  log "  CONTEXT7_ENABLED=$CONTEXT7_ENABLED"
  log "  COPILOT_MCP_CONFIG=$COPILOT_MCP_CONFIG"
  log "  NO_CACHE=$NO_CACHE"
}

load_model_config() {
  local env_plan_set=0 env_plan=""
  local env_review_set=0 env_review=""
  local env_escalation_set=0 env_escalation=""
  local env_timeout_set=0 env_timeout=""
  local env_caffeinate_set=0 env_caffeinate=""
  local env_tool_mode_set=0 env_tool_mode=""
  local env_context7_set=0 env_context7=""
  local env_mcp_config_set=0 env_mcp_config=""
  local env_retries_set=0 env_retries=""
  local env_no_cache_set=0 env_no_cache=""

  if [[ -n "${PLAN_MODEL:-}" ]]; then env_plan_set=1; env_plan="$PLAN_MODEL"; fi
  if [[ -n "${REVIEW_MODEL:-}" ]]; then env_review_set=1; env_review="$REVIEW_MODEL"; fi
  if [[ -n "${REVIEW_ESCALATION_MODEL:-}" ]]; then env_escalation_set=1; env_escalation="$REVIEW_ESCALATION_MODEL"; fi
  if [[ -n "${CODEX_TIMEOUT_MINUTES:-}" ]]; then env_timeout_set=1; env_timeout="$CODEX_TIMEOUT_MINUTES"; fi
  if [[ -n "${ENABLE_CAFFEINATE:-}" ]]; then env_caffeinate_set=1; env_caffeinate="$ENABLE_CAFFEINATE"; fi
  if [[ -n "${COPILOT_TOOL_MODE:-}" ]]; then env_tool_mode_set=1; env_tool_mode="$COPILOT_TOOL_MODE"; fi
  if [[ -n "${CONTEXT7_ENABLED:-}" ]]; then env_context7_set=1; env_context7="$CONTEXT7_ENABLED"; fi
  if [[ -n "${COPILOT_MCP_CONFIG:-}" ]]; then env_mcp_config_set=1; env_mcp_config="$COPILOT_MCP_CONFIG"; fi
  if [[ -n "${MAX_RETRIES:-}" ]]; then env_retries_set=1; env_retries="$MAX_RETRIES"; fi
  if [[ -n "${NO_CACHE:-}" ]]; then env_no_cache_set=1; env_no_cache="$NO_CACHE"; fi

  [[ -f "$MODEL_CONFIG_FILE" ]] || die "Model config file not found: $MODEL_CONFIG_FILE"
  set -a
  # shellcheck source=/dev/null
  source "$MODEL_CONFIG_FILE"
  set +a

  # Re-apply caller-provided environment overrides after sourcing defaults.
  if (( env_plan_set )); then PLAN_MODEL="$env_plan"; fi
  if (( env_review_set )); then REVIEW_MODEL="$env_review"; fi
  if (( env_escalation_set )); then REVIEW_ESCALATION_MODEL="$env_escalation"; fi
  if (( env_timeout_set )); then CODEX_TIMEOUT_MINUTES="$env_timeout"; fi
  if (( env_caffeinate_set )); then ENABLE_CAFFEINATE="$env_caffeinate"; fi
  if (( env_tool_mode_set )); then COPILOT_TOOL_MODE="$env_tool_mode"; fi
  if (( env_context7_set )); then CONTEXT7_ENABLED="$env_context7"; fi
  if (( env_mcp_config_set )); then COPILOT_MCP_CONFIG="$env_mcp_config"; fi
  if (( env_retries_set )); then MAX_RETRIES="$env_retries"; fi
  if (( env_no_cache_set )); then NO_CACHE="$env_no_cache"; fi

  if [[ -z "${COPILOT_MCP_CONFIG:-}" ]]; then
    COPILOT_MCP_CONFIG="$HOME/.copilot/mcp-config.json"
  fi

  require_non_empty_config "PLAN_MODEL" "${PLAN_MODEL:-}"
  require_non_empty_config "REVIEW_MODEL" "${REVIEW_MODEL:-}"
  require_non_empty_config "REVIEW_ESCALATION_MODEL" "${REVIEW_ESCALATION_MODEL:-}"
  require_non_empty_config "CODEX_TIMEOUT_MINUTES" "${CODEX_TIMEOUT_MINUTES:-}"
  require_non_empty_config "ENABLE_CAFFEINATE" "${ENABLE_CAFFEINATE:-}"
  require_non_empty_config "COPILOT_TOOL_MODE" "${COPILOT_TOOL_MODE:-}"
  require_non_empty_config "CONTEXT7_ENABLED" "${CONTEXT7_ENABLED:-}"
  require_non_empty_config "COPILOT_MCP_CONFIG" "${COPILOT_MCP_CONFIG:-}"
  require_non_empty_config "MAX_RETRIES" "${MAX_RETRIES:-}"
  require_non_empty_config "NO_CACHE" "${NO_CACHE:-}"

  require_positive_integer_config "CODEX_TIMEOUT_MINUTES" "$CODEX_TIMEOUT_MINUTES"
  require_positive_integer_config "MAX_RETRIES" "$MAX_RETRIES"
  require_binary_flag_config "ENABLE_CAFFEINATE" "$ENABLE_CAFFEINATE"
  require_binary_flag_config "CONTEXT7_ENABLED" "$CONTEXT7_ENABLED"
  require_binary_flag_config "NO_CACHE" "$NO_CACHE"

  case "$COPILOT_TOOL_MODE" in
    text-only|tools-enabled) ;;
    *) die "Config COPILOT_TOOL_MODE must be text-only or tools-enabled (got: $COPILOT_TOOL_MODE)" ;;
  esac

  export PLAN_MODEL REVIEW_MODEL REVIEW_ESCALATION_MODEL
  export CODEX_TIMEOUT_MINUTES ENABLE_CAFFEINATE COPILOT_TOOL_MODE CONTEXT7_ENABLED COPILOT_MCP_CONFIG MAX_RETRIES NO_CACHE

  if (( VERBOSE )); then
    print_model_routing_table
  fi
}

git_tree_hash() {
  {
    git rev-parse HEAD^{tree} 2>/dev/null || echo "NO_HEAD_TREE"
    git diff --no-color
    git diff --cached --no-color
    git ls-files --others --exclude-standard | sort
  } | shasum -a 256 | awk '{print $1}'
}

cache_key() {
  local phase="$1"
  local model="$2"
  local task_content="$3"
  local tree_hash
  tree_hash="$(git_tree_hash)"
  printf '%s\n%s\n%s\n%s\n' "$phase" "$model" "$task_content" "$tree_hash" \
    | shasum -a 256 \
    | awk '{print $1}'
}

cache_get() {
  local phase="$1"
  local model="$2"
  local key="$3"
  local cache_file="$CACHE_DIR/${key}.txt"

  if [[ "$NO_CACHE" == "1" ]]; then
    return 1
  fi

  if [[ -f "$cache_file" ]]; then
    log "[CACHE HIT] phase=$phase model=$model key=$key"
    cat "$cache_file"
    return 0
  fi

  return 1
}

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

cache_put() {
  local phase="$1"
  local model="$2"
  local key="$3"
  local content="$4"
  local cache_file="$CACHE_DIR/${key}.txt"
  local meta_file="$CACHE_DIR/${key}.meta"
  local git_ref

  if [[ "$NO_CACHE" == "1" ]]; then
    return 0
  fi

  local ts_escaped model_escaped phase_escaped git_ref_escaped task_file_escaped
  mkdir -p "$CACHE_DIR"
  printf '%s' "$content" > "$cache_file"
  git_ref="$(git rev-parse --short HEAD 2>/dev/null || echo "UNBORN")"
  ts_escaped="$(json_escape "$(timestamp)")"
  model_escaped="$(json_escape "$model")"
  phase_escaped="$(json_escape "$phase")"
  git_ref_escaped="$(json_escape "$git_ref")"
  task_file_escaped="$(json_escape "$TASK_FILE")"
  cat > "$meta_file" <<EOF
{"timestamp":"$ts_escaped","model":"$model_escaped","phase":"$phase_escaped","git_ref":"$git_ref_escaped","task_file":"$task_file_escaped"}
EOF
}

run_with_caffeinate_for_codex() {
  if [[ "$ENABLE_CAFFEINATE" == "1" ]] && command -v caffeinate >/dev/null 2>&1; then
    caffeinate -dimsu "$@"
    return
  fi
  "$@"
}

enable_stage_caffeinate_if_needed() {
  local stage="$1"
  case "$stage" in
    plan|build|review|rework|all) ;;
    *) return 0 ;;
  esac

  if [[ "$ENABLE_CAFFEINATE" == "1" ]] && command -v caffeinate >/dev/null 2>&1; then
    # Keep machine awake for the lifetime of this script process.
    caffeinate -dimsu -w $$ >/dev/null 2>&1 &
    log "caffeinate enabled for stage: $stage"
  fi
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

assert_prepare_safe_worktree() {
  local status_lines other_changes
  status_lines="$(git status --porcelain)"
  if [[ -z "$status_lines" ]]; then
    return 0
  fi

  other_changes="$(printf '%s\n' "$status_lines" | awk -v tf="$TASK_FILE" '
    {
      path = substr($0, 4)
      if (path != tf) print $0
    }
  ')"
  if [[ -n "$other_changes" ]]; then
    die "Working tree has changes beyond $TASK_FILE. Commit/stash them before task-prepare."
  fi
}

assert_plan_safe_worktree_for_task_file_only() {
  local status_lines other_changes
  status_lines="$(git status --porcelain)"
  if [[ -z "$status_lines" ]]; then
    return 0
  fi

  other_changes="$(printf '%s\n' "$status_lines" | awk -v tf="$TASK_FILE" '
    {
      path = substr($0, 4)
      if (path != tf) print $0
    }
  ')"
  if [[ -n "$other_changes" ]]; then
    die "Working tree has changes beyond $TASK_FILE. Commit/stash them before task-plan."
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

copilot_installed() {
  if [[ "$CONTEXT7_AVAILABLE_STATE" == "available" ]]; then
    return 0
  fi
  if [[ "$CONTEXT7_AVAILABLE_STATE" == "unavailable" ]]; then
    return 1
  fi

  if command -v copilot >/dev/null 2>&1; then
    CONTEXT7_AVAILABLE_STATE="available"
  else
    CONTEXT7_AVAILABLE_STATE="unavailable"
  fi

  [[ "$CONTEXT7_AVAILABLE_STATE" == "available" ]]
}

context7_configured() {
  local config_file="${COPILOT_MCP_CONFIG:-$HOME/.copilot/mcp-config.json}"
  [[ -f "$config_file" ]] || return 1
  grep -Eiq '"mcpServers"[[:space:]]*:' "$config_file" || return 1
  grep -Eiq '"context7"[[:space:]]*:' "$config_file" || return 1
}

phase_supports_context7() {
  local phase="$1"
  [[ "$phase" == "plan" || "$phase" == "review" ]]
}

should_enable_context7_for_phase() {
  local phase="$1"
  [[ "$CONTEXT7_ENABLED" == "1" ]] || return 1
  phase_supports_context7 "$phase" || return 1

  if ! copilot_installed; then
    if (( CONTEXT7_WARNING_EMITTED == 0 )); then
      log "WARN: CONTEXT7_ENABLED=1 but Copilot CLI is not available. Continuing without Context7."
      CONTEXT7_WARNING_EMITTED=1
    fi
    return 1
  fi

  if ! context7_configured; then
    if (( CONTEXT7_WARNING_EMITTED == 0 )); then
      log "WARN: CONTEXT7_ENABLED=1 but Context7 MCP is not configured in $COPILOT_MCP_CONFIG."
      log "WARN: Add context7 under mcpServers in that file, then rerun."
      CONTEXT7_WARNING_EMITTED=1
    fi
    return 1
  fi

  return 0
}

run_copilot_prompt() {
  local model="$1"
  local prompt="$2"
  local phase="${3:-generic}"
  local base_args=(
    copilot
    --model "$model"
    -p "$prompt"
    --no-color
  )
  local args_with_context7 args_without_context7 output_file error_file rc

  if [[ "$COPILOT_TOOL_MODE" == "text-only" ]]; then
    # Keep planning/review deterministic and avoid Copilot CLI tool permission failures.
    args_without_context7=(
      "${base_args[@]}"
      --no-ask-user
      --disable-builtin-mcps
      --deny-tool write
      --deny-tool shell
      --deny-tool url
    )

    if should_enable_context7_for_phase "$phase"; then
      args_with_context7=(
        "${base_args[@]}"
        --no-ask-user
        --allow-tool context7
        --deny-tool write
        --deny-tool shell
        --deny-tool url
      )

      output_file="$(mktemp)"
      error_file="$(mktemp)"
      set +e
      "${args_with_context7[@]}" >"$output_file" 2>"$error_file"
      rc=$?
      set -e
      if [[ "$rc" -eq 0 ]]; then
        if (( VERBOSE )) && [[ -s "$error_file" ]]; then
          log "Context7 stderr output (first 20 lines):"
          sed -n '1,20p' "$error_file" >&2
        fi
        cat "$output_file"
        rm -f "$output_file"
        rm -f "$error_file"
        return 0
      fi

      if (( CONTEXT7_WARNING_EMITTED == 0 )); then
        log "WARN: Context7 tool invocation failed. Falling back without Context7 for this run."
        log "WARN: Configure an MCP tool named 'context7' in $COPILOT_MCP_CONFIG, then rerun with CONTEXT7_ENABLED=1."
        CONTEXT7_WARNING_EMITTED=1
      fi
      if (( VERBOSE )); then
        log "Context7 failure output (first 20 lines):"
        sed -n '1,20p' "$error_file" >&2
      fi
      rm -f "$output_file"
      rm -f "$error_file"
      "${args_without_context7[@]}"
      return 0
    fi

    "${args_without_context7[@]}"
    return 0
  fi

  "${base_args[@]}"
}

run_copilot_prompt_visible() {
  local model="$1"
  local prompt="$2"
  local phase="${3:-generic}"
  run_copilot_prompt "$model" "$prompt" "$phase" 2>&1 | tee /dev/stderr
}

run_copilot_prompt_with_cache() {
  local phase="$1"
  local model="$2"
  local prompt="$3"
  local task_content="$4"
  local visible="${5:-0}"
  local key output

  key="$(cache_key "$phase" "$model" "$task_content")"
  if output="$(cache_get "$phase" "$model" "$key")"; then
    printf '%s' "$output"
    return 0
  fi

  if [[ "$visible" == "1" ]]; then
    output="$(run_copilot_prompt_visible "$model" "$prompt" "$phase")"
  else
    output="$(run_copilot_prompt "$model" "$prompt" "$phase")"
  fi

  cache_put "$phase" "$model" "$key" "$output"
  printf '%s' "$output"
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

normalize_workflow_commands_in_task_file() {
  local content="$1"
  local without_existing
  without_existing="$(printf '%s\n' "$content" | awk '
    BEGIN { skip=0 }
    /^## Workflow Commands[[:space:]]*$/ { skip=1; next }
    skip && /^## / { skip=0 }
    !skip { print }
  ')"
  cat <<EOF
$without_existing

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

run_with_retries_and_codex_fix() {
  local label="$1"
  shift
  local cmd=("$@")
  local cmd_str attempt rc output_file output prompt
  printf -v cmd_str '%q ' "${cmd[@]}"
  cmd_str="${cmd_str% }"

  for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
    log "$label (attempt $attempt/$MAX_RETRIES)"
    output_file="$(mktemp)"
    set +e
    "${cmd[@]}" 2>&1 | tee "$output_file"
    rc=${PIPESTATUS[0]}
    set -e
    if [[ "$rc" -eq 0 ]]; then
      rm -f "$output_file"
      return 0
    fi

    output="$(sed -n '1,1200p' "$output_file")"
    rm -f "$output_file"
    append_retry_log "$label failed on attempt $attempt with exit code $rc: $cmd_str"

    if (( attempt == MAX_RETRIES )); then
      append_retry_log "$label failed after $MAX_RETRIES attempts."
      return 1
    fi

    prompt="$(cat <<EOF
Fix the failing verification command in the current branch.

Task file: $TASK_FILE
Failed command: $cmd_str
Attempt: $attempt of $MAX_RETRIES
Exit code: $rc

Failure output (truncated):
$output

Constraints:
1) Keep changes minimal and scoped to resolving this failure.
2) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
3) If task file updates are needed, update only mutable sections.
4) After changes, run only this command to validate:
   $cmd_str
EOF
)"
    log "Invoking Codex auto-fix for: $label"
    set +e
    run_codex_prompt "$prompt"
    rc=$?
    set -e
    if [[ "$rc" -ne 0 ]]; then
      append_retry_log "Codex auto-fix failed for '$label' on attempt $attempt with exit code $rc."
    fi
  done
}

run_verification_suite() {
  run_with_retries_and_codex_fix "make lint" make lint
  run_with_retries_and_codex_fix "make typecheck" make typecheck
  run_with_retries_and_codex_fix "make test-backend" make test-backend
  run_with_retries_and_codex_fix "make test-frontend" make test-frontend
  if [[ -f "$REPO_ROOT/web/playwright.config.ts" || -f "$REPO_ROOT/web/playwright.config.js" ]]; then
    run_with_retries_and_codex_fix "make e2e" make e2e
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

cmd_prepare() {
  require_tool git
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE. Create it first."
  assert_prepare_safe_worktree

  local task_snapshot
  task_snapshot="$(mktemp)"
  cp "$TASK_FILE" "$task_snapshot"

  prepare_branch_from_main
  mkdir -p "$(dirname "$TASK_FILE")"
  cp "$task_snapshot" "$TASK_FILE"
  rm -f "$task_snapshot"
  assert_task_path_writable

  commit_and_push_task_file "chore: bootstrap issue #${ISSUE_ID} task file"
  log "Branch ready for planning: $BRANCH"
}

cmd_plan() {
  require_tool git
  require_tool copilot
  validate_task_file "$1"

  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current_branch" == "$BRANCH" ]]; then
    assert_plan_safe_worktree_for_task_file_only
    log "Planning on existing branch $BRANCH with task-file-only local changes."
  else
    assert_clean_worktree
    prepare_branch_from_main
  fi

  ensure_task_file_exists
  assert_task_path_writable

  local task_content prompt
  task_content="$(cat "$TASK_FILE")"

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
$task_content
EOF
)"
  local raw_output planned_task
  raw_output="$(run_copilot_prompt_with_cache "plan" "$PLAN_MODEL" "$prompt" "$task_content" "1")"
  planned_task="$(resolve_plan_task_file_output "$raw_output" || true)"
  [[ -n "$planned_task" ]] || die "Planner output did not include a valid task document. No task file changes were written."

  planned_task="$(normalize_workflow_commands_in_task_file "$planned_task")"
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
  local diff_stat diff_names diff_patch task_content prompt
  diff_stat="$(collect_review_diff_stat)"
  diff_names="$(collect_review_diff_names)"
  diff_patch="$(collect_review_diff_patch)"
  task_content="$(cat "$TASK_FILE")"
  prompt="$(cat <<EOF
You are a strict reviewer for CapitalOS.
Primary review model.

Critical constraint:
- Do NOT execute shell/file tools (no git, ls, glob, read/write calls).
- Use only the provided task file and diff context below.

Task file:
$task_content

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
  run_copilot_prompt_with_cache "review" "$REVIEW_MODEL" "$prompt" "$task_content"
}

run_opus_escalation_review() {
  local sonnet_output="$1"
  local diff_patch task_content prompt
  diff_patch="$(collect_review_diff_patch)"
  task_content="$(cat "$TASK_FILE")"
  prompt="$(cat <<EOF
You are the escalation reviewer for CapitalOS.
Primary review from Sonnet is below.

Critical constraint:
- Do NOT execute shell/file tools (no git, ls, glob, read/write calls).
- Use only the provided Sonnet output, task file, and diff context.

Sonnet review:
$sonnet_output

Task file:
$task_content

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
  run_copilot_prompt_with_cache "review" "$REVIEW_ESCALATION_MODEL" "$prompt" "$task_content"
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
  local original_args=("$@")
  local args=()
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "--verbose" ]]; then
      VERBOSE=1
    else
      args+=("$arg")
    fi
  done

  set -- "${args[@]}"
  [[ $# -eq 2 ]] || { usage; exit 1; }
  local cmd="$1"
  local task="$2"
  local rc

  if stage_requires_self_integrity "$cmd" && [[ "${TASK_FLOW_RUNTIME_ACTIVE:-0}" != "1" ]]; then
    activate_runtime_self_integrity "${original_args[@]}"
  fi

  load_model_config
  enable_stage_caffeinate_if_needed "$cmd"

  case "$cmd" in
    prepare) cmd_prepare "$task" ;;
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

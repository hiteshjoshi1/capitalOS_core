#!/usr/bin/env bash
set -euo pipefail

MAX_RETRIES="${MAX_RETRIES-}"
PLAN_MODEL="${PLAN_MODEL-}"
BUILD_MODEL="${BUILD_MODEL-}"
REVIEW_MODEL="${REVIEW_MODEL-}"
REVIEW_ESCALATION_MODEL="${REVIEW_ESCALATION_MODEL-}"
BUILD_MAX_AUTOPILOT_CONTINUES="${BUILD_MAX_AUTOPILOT_CONTINUES-}"
CODEX_TIMEOUT_MINUTES="${CODEX_TIMEOUT_MINUTES-}"
ENABLE_CAFFEINATE="${ENABLE_CAFFEINATE-}"
COPILOT_TOOL_MODE="${COPILOT_TOOL_MODE-}"
CONTEXT7_ENABLED="${CONTEXT7_ENABLED-}"
COPILOT_MCP_CONFIG="${COPILOT_MCP_CONFIG-}"
NO_CACHE="${NO_CACHE-}"
ALLOWED_AUX_FILES="${ALLOWED_AUX_FILES-}"
VERBOSE=0
CONTEXT7_AVAILABLE_STATE=""
CONTEXT7_WARNING_EMITTED=0
REVIEW_VERIFY_SUMMARY=""
REVIEW_VERIFY_DETAILS=""
REVIEW_VERIFY_ANY_FAIL=0
REVIEW_ALLOWED_AUX_FILES_DISPLAY="(none)"
declare -a REVIEW_GIT_PATHSPEC=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${TASK_FLOW_RUNTIME_ACTIVE:-0}" == "1" && -n "${TASK_FLOW_REPO_ROOT:-}" ]]; then
  REPO_ROOT="$TASK_FLOW_REPO_ROOT"
else
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
TASK_TEMPLATE="$REPO_ROOT/tasks/_template.md"
MODEL_CONFIG_FILE="$REPO_ROOT/.ai-models.env"
CACHE_DIR="$REPO_ROOT/.task-cache"
FAILURE_LOG_DIR="$CACHE_DIR/failures"

cd "$REPO_ROOT"

TASK_FILE=""
TASK_BASENAME=""
ISSUE_ID=""
SLUG=""
BRANCH=""

usage() {
  cat <<'EOF'
Usage:
  scripts/task_flow.sh [--verbose] prepare      tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] plan         tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] build        tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] review       tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] review-input tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] rework       tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] ship         tasks/issue-<id>-<slug>.md
  scripts/task_flow.sh [--verbose] all          tasks/issue-<id>-<slug>.md

Environment overrides:
  PLAN_MODEL=<planner model>
  BUILD_MODEL=<builder model>
  REVIEW_MODEL=<primary reviewer model>
  REVIEW_ESCALATION_MODEL=<escalation reviewer model>
  BUILD_MAX_AUTOPILOT_CONTINUES=12
  MAX_RETRIES=3
  CODEX_TIMEOUT_MINUTES=60
  ENABLE_CAFFEINATE=1
  COPILOT_TOOL_MODE=text-only
  CONTEXT7_ENABLED=0
  COPILOT_MCP_CONFIG=~/.copilot/mcp-config.json
  NO_CACHE=0
  ALLOWED_AUX_FILES=scripts/task_flow.sh
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
    plan|build|review|review-input|rework|all) return 0 ;;
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
  log "  BUILD_MODEL=$BUILD_MODEL"
  log "  REVIEW_MODEL=$REVIEW_MODEL"
  log "  REVIEW_ESCALATION_MODEL=$REVIEW_ESCALATION_MODEL"
  log "  BUILD_MAX_AUTOPILOT_CONTINUES=$BUILD_MAX_AUTOPILOT_CONTINUES"
  log "  CODEX_TIMEOUT_MINUTES=$CODEX_TIMEOUT_MINUTES"
  log "  MAX_RETRIES=$MAX_RETRIES"
  log "  COPILOT_TOOL_MODE=$COPILOT_TOOL_MODE"
  log "  CONTEXT7_ENABLED=$CONTEXT7_ENABLED"
  log "  COPILOT_MCP_CONFIG=$COPILOT_MCP_CONFIG"
  log "  NO_CACHE=$NO_CACHE"
  log "  ALLOWED_AUX_FILES=${ALLOWED_AUX_FILES:-<none>}"
}

load_model_config() {
  local env_plan_set=0 env_plan=""
  local env_build_set=0 env_build=""
  local env_review_set=0 env_review=""
  local env_escalation_set=0 env_escalation=""
  local env_build_autopilot_set=0 env_build_autopilot=""
  local env_timeout_set=0 env_timeout=""
  local env_caffeinate_set=0 env_caffeinate=""
  local env_tool_mode_set=0 env_tool_mode=""
  local env_context7_set=0 env_context7=""
  local env_mcp_config_set=0 env_mcp_config=""
  local env_retries_set=0 env_retries=""
  local env_no_cache_set=0 env_no_cache=""
  local env_allowed_aux_set=0 env_allowed_aux=""

  if [[ -n "${PLAN_MODEL:-}" ]]; then env_plan_set=1; env_plan="$PLAN_MODEL"; fi
  if [[ -n "${BUILD_MODEL:-}" ]]; then env_build_set=1; env_build="$BUILD_MODEL"; fi
  if [[ -n "${REVIEW_MODEL:-}" ]]; then env_review_set=1; env_review="$REVIEW_MODEL"; fi
  if [[ -n "${REVIEW_ESCALATION_MODEL:-}" ]]; then env_escalation_set=1; env_escalation="$REVIEW_ESCALATION_MODEL"; fi
  if [[ -n "${BUILD_MAX_AUTOPILOT_CONTINUES:-}" ]]; then env_build_autopilot_set=1; env_build_autopilot="$BUILD_MAX_AUTOPILOT_CONTINUES"; fi
  if [[ -n "${CODEX_TIMEOUT_MINUTES:-}" ]]; then env_timeout_set=1; env_timeout="$CODEX_TIMEOUT_MINUTES"; fi
  if [[ -n "${ENABLE_CAFFEINATE:-}" ]]; then env_caffeinate_set=1; env_caffeinate="$ENABLE_CAFFEINATE"; fi
  if [[ -n "${COPILOT_TOOL_MODE:-}" ]]; then env_tool_mode_set=1; env_tool_mode="$COPILOT_TOOL_MODE"; fi
  if [[ -n "${CONTEXT7_ENABLED:-}" ]]; then env_context7_set=1; env_context7="$CONTEXT7_ENABLED"; fi
  if [[ -n "${COPILOT_MCP_CONFIG:-}" ]]; then env_mcp_config_set=1; env_mcp_config="$COPILOT_MCP_CONFIG"; fi
  if [[ -n "${MAX_RETRIES:-}" ]]; then env_retries_set=1; env_retries="$MAX_RETRIES"; fi
  if [[ -n "${NO_CACHE:-}" ]]; then env_no_cache_set=1; env_no_cache="$NO_CACHE"; fi
  if [[ -n "${ALLOWED_AUX_FILES:-}" ]]; then env_allowed_aux_set=1; env_allowed_aux="$ALLOWED_AUX_FILES"; fi

  [[ -f "$MODEL_CONFIG_FILE" ]] || die "Model config file not found: $MODEL_CONFIG_FILE"
  set -a
  # shellcheck source=/dev/null
  source "$MODEL_CONFIG_FILE"
  set +a

  if (( env_plan_set )); then PLAN_MODEL="$env_plan"; fi
  if (( env_build_set )); then BUILD_MODEL="$env_build"; fi
  if (( env_review_set )); then REVIEW_MODEL="$env_review"; fi
  if (( env_escalation_set )); then REVIEW_ESCALATION_MODEL="$env_escalation"; fi
  if (( env_build_autopilot_set )); then BUILD_MAX_AUTOPILOT_CONTINUES="$env_build_autopilot"; fi
  if (( env_timeout_set )); then CODEX_TIMEOUT_MINUTES="$env_timeout"; fi
  if (( env_caffeinate_set )); then ENABLE_CAFFEINATE="$env_caffeinate"; fi
  if (( env_tool_mode_set )); then COPILOT_TOOL_MODE="$env_tool_mode"; fi
  if (( env_context7_set )); then CONTEXT7_ENABLED="$env_context7"; fi
  if (( env_mcp_config_set )); then COPILOT_MCP_CONFIG="$env_mcp_config"; fi
  if (( env_retries_set )); then MAX_RETRIES="$env_retries"; fi
  if (( env_no_cache_set )); then NO_CACHE="$env_no_cache"; fi
  if (( env_allowed_aux_set )); then ALLOWED_AUX_FILES="$env_allowed_aux"; fi

  if [[ -z "${COPILOT_MCP_CONFIG:-}" ]]; then
    COPILOT_MCP_CONFIG="$HOME/.copilot/mcp-config.json"
  fi

  require_non_empty_config "PLAN_MODEL" "${PLAN_MODEL:-}"
  require_non_empty_config "BUILD_MODEL" "${BUILD_MODEL:-}"
  require_non_empty_config "REVIEW_MODEL" "${REVIEW_MODEL:-}"
  require_non_empty_config "REVIEW_ESCALATION_MODEL" "${REVIEW_ESCALATION_MODEL:-}"
  require_non_empty_config "BUILD_MAX_AUTOPILOT_CONTINUES" "${BUILD_MAX_AUTOPILOT_CONTINUES:-}"
  require_non_empty_config "CODEX_TIMEOUT_MINUTES" "${CODEX_TIMEOUT_MINUTES:-}"
  require_non_empty_config "ENABLE_CAFFEINATE" "${ENABLE_CAFFEINATE:-}"
  require_non_empty_config "COPILOT_TOOL_MODE" "${COPILOT_TOOL_MODE:-}"
  require_non_empty_config "CONTEXT7_ENABLED" "${CONTEXT7_ENABLED:-}"
  require_non_empty_config "COPILOT_MCP_CONFIG" "${COPILOT_MCP_CONFIG:-}"
  require_non_empty_config "MAX_RETRIES" "${MAX_RETRIES:-}"
  require_non_empty_config "NO_CACHE" "${NO_CACHE:-}"

  require_positive_integer_config "BUILD_MAX_AUTOPILOT_CONTINUES" "$BUILD_MAX_AUTOPILOT_CONTINUES"
  require_positive_integer_config "CODEX_TIMEOUT_MINUTES" "$CODEX_TIMEOUT_MINUTES"
  require_positive_integer_config "MAX_RETRIES" "$MAX_RETRIES"
  require_binary_flag_config "ENABLE_CAFFEINATE" "$ENABLE_CAFFEINATE"
  require_binary_flag_config "CONTEXT7_ENABLED" "$CONTEXT7_ENABLED"
  require_binary_flag_config "NO_CACHE" "$NO_CACHE"

  case "$COPILOT_TOOL_MODE" in
    text-only|tools-enabled) ;;
    *) die "Config COPILOT_TOOL_MODE must be text-only or tools-enabled (got: $COPILOT_TOOL_MODE)" ;;
  esac

  export PLAN_MODEL BUILD_MODEL REVIEW_MODEL REVIEW_ESCALATION_MODEL
  export BUILD_MAX_AUTOPILOT_CONTINUES
  export CODEX_TIMEOUT_MINUTES ENABLE_CAFFEINATE COPILOT_TOOL_MODE CONTEXT7_ENABLED COPILOT_MCP_CONFIG MAX_RETRIES NO_CACHE ALLOWED_AUX_FILES

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
    plan|build|review|review-input|rework|all) ;;
    *) return 0 ;;
  esac

  if [[ "$ENABLE_CAFFEINATE" == "1" ]] && command -v caffeinate >/dev/null 2>&1; then
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

replace_latest_named_text_block() {
  local title="$1"
  local body="$2"

  TITLE="$title" BODY="$body" TASK_PATH="$TASK_FILE" python3 - <<'PY'
import os
from pathlib import Path

task_path = Path(os.environ["TASK_PATH"])
title = os.environ["TITLE"]
body = os.environ["BODY"]

text = task_path.read_text()
lines = text.splitlines()

match_indices = []
for i, line in enumerate(lines):
    if line == f"### {title}" or line.startswith(f"### {title} ("):
        match_indices.append(i)

if not match_indices:
    raise SystemExit(1)

start = match_indices[-1]

fence_start = None
fence_end = None
for i in range(start + 1, len(lines)):
    if lines[i].strip() == "```text":
        fence_start = i
        break

if fence_start is None:
    raise SystemExit(1)

for i in range(fence_start + 1, len(lines)):
    if lines[i].strip() == "```":
        fence_end = i
        break

if fence_end is None:
    raise SystemExit(1)

new_block = lines[:fence_start + 1] + body.rstrip("\n").splitlines() + ["```"] + lines[fence_end + 1:]
task_path.write_text("\n".join(new_block) + "\n")
PY
}

append_retry_log() {
  local body="$1"
  append_task_block "Retry Entry" "$body"
}

sanitize_label_for_filename() {
  printf '%s' "$1" | tr ' /:' '---' | tr -cd '[:alnum:]_.-'
}

persist_failure_output() {
  local label="$1"
  local command="$2"
  local attempt="$3"
  local exit_code="$4"
  local output="$5"
  local safe_label ts file_path

  safe_label="$(sanitize_label_for_filename "$label")"
  ts="$(date -u +"%Y%m%dT%H%M%SZ")"
  mkdir -p "$FAILURE_LOG_DIR"
  file_path="$FAILURE_LOG_DIR/${ts}_${safe_label}_attempt${attempt}.log"

  {
    echo "timestamp=$(timestamp)"
    echo "label=$label"
    echo "command=$command"
    echo "attempt=$attempt"
    echo "exit_code=$exit_code"
    echo "----- output -----"
    printf '%s\n' "$output"
  } >"$file_path"

  printf '%s\n' "$file_path"
}

classify_failure_output() {
  local output="$1"

  if grep -Eiq \
    'permission denied while trying to connect to the docker daemon socket|docker\.sock:.*operation not permitted|cannot connect to the docker daemon|unable to get image|pull access denied|failed to solve.*network|connection refused|temporary failure in name resolution|no such host|network is unreachable|dial tcp: lookup|tls handshake timeout|i/o timeout|context deadline exceeded|proxyconnect tcp|x509:' \
    <<<"$output"; then
    echo "INFRA"
    return 0
  fi

  echo "CODE"
}

path_fingerprint() {
  local path="$1"
  if [[ -e "$path" ]]; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    echo "__ABSENT__"
  fi
}

collect_paths_fingerprint_snapshot() {
  local paths="$1"
  local path
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    printf '%s\t%s\n' "$path" "$(path_fingerprint "$path")"
  done <<<"$paths"
}

snapshot_fingerprint_for_path() {
  local snapshot="$1"
  local path="$2"
  awk -F'\t' -v p="$path" '$1 == p { print $2; found=1; exit } END { if (!found) print "" }' <<<"$snapshot"
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

extract_latest_named_text_block() {
  local title_prefix="$1"
  awk -v prefix="### " -v title="$title_prefix" '
    function starts_with(s, p) { return index(s, p) == 1 }
    /^### / {
      capture_title = (starts_with($0, prefix title " (") || $0 == (prefix title))
      in_block = 0
      next
    }
    capture_title && /^```text$/ {
      in_block = 1
      block = ""
      next
    }
    capture_title && in_block && /^```$/ {
      last = block
      capture_title = 0
      in_block = 0
      next
    }
    capture_title && in_block {
      block = block $0 ORS
    }
    END {
      if (length(last) > 0) {
        printf "%s", last
      }
    }
  ' "$TASK_FILE"
}

extract_markdown_section_body() {
  local heading="$1"
  awk -v section="## " -v heading="$heading" '
    $0 == (section heading) { capture=1; next }
    capture && /^## / { exit }
    capture { print }
  ' "$TASK_FILE"
}

extract_single_line_field() {
  local body="$1"
  local field="$2"
  printf '%s\n' "$body" | awk -F':' -v key="$field" '
    toupper($1) == toupper(key) {
      sub(/^[^:]*:[[:space:]]*/, "", $0)
      print
      exit
    }
  '
}

extract_analysis_field_value() {
  local body="$1"
  local field="$2"
  local value=""

  value="$(extract_single_line_field "$body" "$field")"
  if [[ -n "${value// }" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  case "$field" in
    PLANNED_CHANGES)
      value="$(extract_single_line_field "$body" "CHANGE_MADE")"
      [[ -n "${value// }" ]] || value="$(extract_single_line_field "$body" "PLANNED_CHANGE")"
      ;;
    VALIDATION_PLAN)
      value="$(extract_single_line_field "$body" "VALIDATION_PERFORMED")"
      ;;
    FINDINGS_ADDRESSED)
      value="$(extract_single_line_field "$body" "FINDINGS_RESOLVED")"
      ;;
  esac

  printf '%s\n' "$value"
}

append_review_human_input_placeholder() {
  local review_id="$1"

  if [[ -n "$(extract_latest_named_text_block "Review Cycle ${review_id} - Human Input")" ]]; then
    log "Human input block already exists for ${review_id}; not appending duplicate."
    return 0
  fi

  append_task_block "Review Cycle ${review_id} - Human Input" "Reviewed: <your-name>
Status: <PENDING|IN_PROGRESS|COMPLETE>
HUMAN_QUESTIONS:
- <question 1>
- <question 2>

RESPONSE_REQUIREMENTS:
- <what the rework output must explicitly answer>
- <what evidence is required>

UNRESOLVED_COMMENTS:
- <comment 1>
- <comment 2>"
}

ensure_rework_human_input_block_ready() {
  local review_id="$1"
  local block reviewed status questions unresolved requirements

  block="$(extract_latest_named_text_block "Review Cycle ${review_id} - Human Input")"
  if [[ -z "$block" ]]; then
    append_review_human_input_placeholder "$review_id"
    die "Missing structured human input for ${review_id}. Fill 'Review Cycle ${review_id} - Human Input' and rerun task-rework.
Hint: run make task-review-input TASK=$TASK_FILE"
  fi

  reviewed="$(extract_single_line_field "$block" "REVIEWED")"
  status="$(extract_single_line_field "$block" "STATUS")"
  questions="$(extract_single_line_field "$block" "HUMAN_QUESTIONS")"
  unresolved="$(extract_single_line_field "$block" "UNRESOLVED_COMMENTS")"
  requirements="$(extract_single_line_field "$block" "RESPONSE_REQUIREMENTS")"

  [[ -n "${reviewed// }" ]] || die "Review cycle ${review_id} human input is missing Reviewed/REVIEWED."
  [[ -n "${status// }" ]] || die "Review cycle ${review_id} human input is missing Status/STATUS."

  grep -Eq '^(HUMAN_QUESTIONS):' <<<"$block" || die "Review cycle ${review_id} human input is missing HUMAN_QUESTIONS section."
  grep -Eq '^(UNRESOLVED_COMMENTS):' <<<"$block" || die "Review cycle ${review_id} human input is missing UNRESOLVED_COMMENTS section."
  grep -Eq '^(RESPONSE_REQUIREMENTS):' <<<"$block" || die "Review cycle ${review_id} human input is missing RESPONSE_REQUIREMENTS section."

  if ! grep -Eiq '^Reviewed:[[:space:]]*[^<].*$|^REVIEWED:[[:space:]]*yes$' <<<"$block"; then
    die "Review cycle ${review_id} human input must be explicitly filled before rework."
  fi

  [[ -n "${questions// }" ]] || die "Review cycle ${review_id} human input is missing HUMAN_QUESTIONS."
  [[ "$questions" != "<required>" ]] || die "Review cycle ${review_id} HUMAN_QUESTIONS still has placeholder text."
  [[ -n "${unresolved// }" ]] || die "Review cycle ${review_id} human input is missing UNRESOLVED_COMMENTS."
  [[ "$unresolved" != "<required>" ]] || die "Review cycle ${review_id} UNRESOLVED_COMMENTS still has placeholder text."
  [[ -n "${requirements// }" ]] || die "Review cycle ${review_id} human input is missing RESPONSE_REQUIREMENTS."
  [[ "$requirements" != "<required>" ]] || die "Review cycle ${review_id} RESPONSE_REQUIREMENTS still has placeholder text."
}

cmd_review_input() {
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

  local review_id
  review_id="$(latest_review_id || true)"
  [[ -n "$review_id" ]] || die "No review cycle found. Run task-review first."

  append_review_human_input_placeholder "$review_id"
  log "Appended review input placeholder for ${review_id} in $TASK_FILE"
}

ensure_rework_analysis_and_matrix_present() {
  local review_id="$1"
  local analysis_block matrix_block

  analysis_block="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Analysis")"
  if [[ -z "$analysis_block" ]]; then
    die "Missing rework analysis block for ${review_id}. Run task-rework analysis pass first."
  fi

  matrix_block="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Answer Matrix")"
  if [[ -z "$matrix_block" ]]; then
    die "Missing rework answer matrix for ${review_id}. Run task-rework analysis pass first."
  fi
}

validate_rework_analysis_and_matrix() {
  local review_id="$1"
  local analysis_block matrix_block value
  local analysis_fields matrix_fields

  ensure_rework_analysis_and_matrix_present "$review_id"

  analysis_block="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Analysis")"
  matrix_block="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Answer Matrix")"

  analysis_fields=(
    ROOT_CAUSE
    FINDINGS_ADDRESSED
    PLANNED_CHANGES
    VALIDATION_PLAN
    UNRESOLVED_ASSUMPTIONS
  )
  for field in "${analysis_fields[@]}"; do
    value="$(extract_analysis_field_value "$analysis_block" "$field")"
    [[ -n "${value// }" ]] || die "Rework analysis for ${review_id} missing ${field}."
    [[ "$value" != "<required>" ]] || die "Rework analysis for ${review_id} still has placeholder in ${field}."
  done

  grep -Eq '^ENTRY([[:space:]]+|[[:space:]]*:[[:space:]]*)[0-9][0-9]*$' <<<"$matrix_block" || die "Rework answer matrix for ${review_id} must include at least one ENTRY block."
  matrix_fields=(
    REVIEWER_FINDING
    HUMAN_COMMENT
    ROOT_CAUSE
    CHANGE_MADE
    VERIFICATION_PERFORMED
    STATUS
  )
  for field in "${matrix_fields[@]}"; do
    value="$(extract_single_line_field "$matrix_block" "$field")"
    [[ -n "${value// }" ]] || die "Rework answer matrix for ${review_id} missing ${field}."
    [[ "$value" != "<required>" ]] || die "Rework answer matrix for ${review_id} still has placeholder in ${field}."
  done
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

assert_human_approval_gate_passed() {
  is_human_approved || die "Build blocked: Human Approval Gate is not approved in $TASK_FILE."
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
  die "Stage changes before review (use scoped staging for task files), then rerun task-review."
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
        rm -f "$output_file" "$error_file"
        return 0
      fi

      if (( CONTEXT7_WARNING_EMITTED == 0 )); then
        log "WARN: Context7 tool invocation failed. Falling back without Context7 for this run."
        log "WARN: Configure an MCP tool named 'context7' in $COPILOT_MCP_CONFIG, then rerun with CONTEXT7_ENABLED=1."
        CONTEXT7_WARNING_EMITTED=1
      fi
      if (( VERBOSE )) && [[ -s "$error_file" ]]; then
        log "Context7 failure output (first 20 lines):"
        sed -n '1,20p' "$error_file" >&2
      fi
      rm -f "$output_file" "$error_file"
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
  grep -q '^## Human Rework Input \(Mutable\)' <<<"$content" || return 1
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
make task-review-input TASK=$TASK_FILE
make task-rework TASK=$TASK_FILE
make task-ship TASK=$TASK_FILE
\`\`\`
EOF
}

run_builder_prompt() {
  local prompt="$1"
  local args=(
    copilot
    --model "$BUILD_MODEL"
    --autopilot
    --allow-all
    --max-autopilot-continues "$BUILD_MAX_AUTOPILOT_CONTINUES"
    --no-ask-user
    --no-color
    --silent
    -p "$prompt"
  )

  if command -v timeout >/dev/null 2>&1; then
    run_with_caffeinate_for_codex timeout "${CODEX_TIMEOUT_MINUTES}m" "${args[@]}"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    run_with_caffeinate_for_codex gtimeout "${CODEX_TIMEOUT_MINUTES}m" "${args[@]}"
    return
  fi
  run_with_caffeinate_for_codex "${args[@]}"
}

collect_current_changed_paths() {
  {
    git diff --name-only || true
    git diff --cached --name-only || true
    git ls-files --others --exclude-standard || true
  } | awk 'NF' | sed 's#^\./##' | sort -u
}

collect_task_declared_paths() {
  [[ -f "$TASK_FILE" ]] || return 0
  grep -oE '`[^`]+`' "$TASK_FILE" 2>/dev/null \
    | sed -E 's/^`//; s/`$//' \
    | awk '
      NF == 0 { next }
      index($0, " ") > 0 { next }
      $0 ~ /^https?:\/\// { next }
      $0 ~ /^\// { next }
      $0 ~ /^make$/ { next }
      index($0, "/") == 0 { next }
      { print }
    ' \
    | sed 's#^\./##' \
    | sort -u
}

collect_allowed_aux_paths() {
  [[ -n "${ALLOWED_AUX_FILES:-}" ]] || return 0
  printf '%s\n' "$ALLOWED_AUX_FILES" | tr ',;' '\n' | awk '{$1=$1}; NF' | sed 's#^\./##' | sort -u
}

build_autofix_scope_allowlist() {
  {
    printf '%s\n' "$TASK_FILE"
    collect_task_declared_paths
    collect_allowed_aux_paths
  } | awk 'NF' | sed 's#^\./##' | sort -u
}

is_path_allowlisted() {
  local path="$1"
  local allowed_paths="$2"
  local allowed

  while IFS= read -r allowed; do
    [[ -n "$allowed" ]] || continue
    if [[ "$allowed" == */ ]]; then
      [[ "$path" == "$allowed"* ]] && return 0
      continue
    fi
    if [[ -d "$allowed" ]]; then
      [[ "$path" == "$allowed/"* || "$path" == "$allowed" ]] && return 0
      continue
    fi
    [[ "$path" == "$allowed" ]] && return 0
  done <<<"$allowed_paths"
  return 1
}

find_out_of_scope_touched_paths() {
  local baseline_paths="$1"
  local baseline_snapshot="$2"
  local after_paths="$3"
  local allowed_paths="$4"
  local new_paths path before_fp after_fp

  new_paths="$(comm -13 \
    <(printf '%s\n' "$baseline_paths" | awk 'NF' | sort -u) \
    <(printf '%s\n' "$after_paths" | awk 'NF' | sort -u) \
  )"

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if ! is_path_allowlisted "$path" "$allowed_paths"; then
      printf '%s\n' "$path"
    fi
  done <<<"$new_paths"

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if is_path_allowlisted "$path" "$allowed_paths"; then
      continue
    fi
    before_fp="$(snapshot_fingerprint_for_path "$baseline_snapshot" "$path")"
    after_fp="$(path_fingerprint "$path")"
    if [[ "$before_fp" != "$after_fp" ]]; then
      printf '%s\n' "$path"
    fi
  done <<<"$baseline_paths"
}

stage_scoped_changes() {
  local stage_label="$1"
  local strict_mode="${2:-1}"
  local allowed_paths changed_paths blocked_paths path

  allowed_paths="$(build_autofix_scope_allowlist)"
  changed_paths="$(collect_current_changed_paths)"
  blocked_paths=""

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if is_path_allowlisted "$path" "$allowed_paths"; then
      git add -- "$path"
    else
      blocked_paths+="$path"$'\n'
    fi
  done <<<"$changed_paths"

  if [[ -n "${blocked_paths// }" ]]; then
    blocked_paths="$(printf '%s\n' "$blocked_paths" | awk 'NF' | sort -u)"
    append_retry_log "Scope stage gate skipped out-of-scope files during ${stage_label}:
$blocked_paths"
    if [[ "$strict_mode" == "1" ]]; then
      die "Out-of-scope files detected during ${stage_label}:
$blocked_paths
Review/discard these edits or explicitly allow them (ALLOWED_AUX_FILES / task plan), then rerun."
    fi
    log "Skipped out-of-scope files during ${stage_label}."
  fi
}

run_with_retries_and_builder_fix() {
  local label="$1"
  shift
  local cmd=("$@")
  local cmd_str rc output_file output prompt failure_class failure_log
  local baseline_paths baseline_snapshot after_paths allowed_paths out_of_scope_paths
  local auto_fix_rc
  printf -v cmd_str '%q ' "${cmd[@]}"
  cmd_str="${cmd_str% }"

  log "$label (attempt 1/$MAX_RETRIES)"
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
  failure_log="$(persist_failure_output "$label" "$cmd_str" "1" "$rc" "$output")"
  append_retry_log "$label failed on attempt 1 with exit code $rc: $cmd_str
Failure log: $failure_log"
  failure_class="$(classify_failure_output "$output")"
  if [[ "$failure_class" == "INFRA" ]]; then
    append_retry_log "Infra failure detected for '$label'. Auto-fix skipped."
    die "Detected infrastructure/environment failure for '$label' (not a code failure).
Check Docker daemon/socket/network health, then rerun.
Failure log: $failure_log"
  fi

  if (( MAX_RETRIES >= 2 )); then
    log "$label (attempt 2/$MAX_RETRIES, unchanged rerun)"
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
    failure_log="$(persist_failure_output "$label" "$cmd_str" "2" "$rc" "$output")"
    append_retry_log "$label failed on attempt 2 with exit code $rc: $cmd_str
Failure log: $failure_log"
    failure_class="$(classify_failure_output "$output")"
    if [[ "$failure_class" == "INFRA" ]]; then
      append_retry_log "Infra failure detected for '$label' on unchanged rerun. Auto-fix skipped."
      die "Detected infrastructure/environment failure for '$label' on unchanged rerun.
Check Docker daemon/socket/network health, then rerun.
Failure log: $failure_log"
    fi
  else
    append_retry_log "$label failed and MAX_RETRIES=$MAX_RETRIES does not allow unchanged rerun/auto-fix."
    return 1
  fi

  if (( MAX_RETRIES < 3 )); then
    append_retry_log "$label failed after unchanged rerun. MAX_RETRIES=$MAX_RETRIES prevents auto-fix."
    return 1
  fi

  allowed_paths="$(build_autofix_scope_allowlist)"
  prompt="$(cat <<EOF
Fix the failing verification command in the current branch.

Task file: $TASK_FILE
Failed command: $cmd_str
Attempt: 3 of $MAX_RETRIES
Exit code: $rc

Failure output (truncated):
$output

Allowed write paths (strict):
$allowed_paths

Constraints:
1) Keep changes minimal and scoped to resolving this failure.
2) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
3) If task file updates are needed, update only mutable sections.
4) After changes, run only this command to validate:
   $cmd_str
5) Do not modify files outside the allowed write paths list.
EOF
)"
  log "Invoking builder auto-fix for: $label"
  baseline_paths="$(collect_current_changed_paths)"
  baseline_snapshot="$(collect_paths_fingerprint_snapshot "$baseline_paths")"
  set +e
  run_builder_prompt "$prompt"
  auto_fix_rc=$?
  set -e
  if [[ "$auto_fix_rc" -ne 0 ]]; then
    append_retry_log "Builder auto-fix process failed for '$label' with exit code $auto_fix_rc."
    return 1
  fi

  after_paths="$(collect_current_changed_paths)"
  out_of_scope_paths="$(find_out_of_scope_touched_paths "$baseline_paths" "$baseline_snapshot" "$after_paths" "$allowed_paths" | awk 'NF' | sort -u)"
  if [[ -n "${out_of_scope_paths// }" ]]; then
    append_retry_log "Scope gate blocked auto-fix for '$label'. Out-of-scope files touched:
$out_of_scope_paths"
    die "Auto-fix touched out-of-scope files for '$label':
$out_of_scope_paths
Review/discard these edits or explicitly allow them (ALLOWED_AUX_FILES / task plan), then rerun."
  fi

  log "$label (attempt 3/$MAX_RETRIES, post-fix validation)"
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
  failure_log="$(persist_failure_output "$label" "$cmd_str" "3" "$rc" "$output")"
  append_retry_log "$label failed on attempt 3 with exit code $rc: $cmd_str
Failure log: $failure_log"
  append_retry_log "$label failed after one unchanged rerun + one auto-fix cycle."
  return 1
}

run_verification_suite() {
  run_with_retries_and_builder_fix "make lint" make lint
  run_with_retries_and_builder_fix "make typecheck" make typecheck
  run_with_retries "make api-rebuild (fresh backend image)" make api-rebuild
  run_with_retries_and_builder_fix "make test-backend" make test-backend
  run_with_retries_and_builder_fix "make test-frontend" make test-frontend
  run_with_retries_and_builder_fix "make api-smoke (runtime)" make api-smoke
  if [[ -f "$REPO_ROOT/web/playwright.config.ts" || -f "$REPO_ROOT/web/playwright.config.js" ]]; then
    run_with_retries_and_builder_fix "make e2e" make e2e
  else
    append_task_block "Verification Note" "Playwright not configured; skipped make e2e."
  fi
}

run_review_command_capture() {
  local label="$1"
  shift
  local cmd=("$@")
  local output_file rc status output full_output cmd_str failure_log

  output_file="$(mktemp)"
  printf -v cmd_str '%q ' "${cmd[@]}"
  cmd_str="${cmd_str% }"

  set +e
  "${cmd[@]}" >"$output_file" 2>&1
  rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    status="PASS"
  else
    status="FAIL"
    REVIEW_VERIFY_ANY_FAIL=1
  fi

  full_output="$(cat "$output_file")"
  output="$(sed -n '1,240p' "$output_file")"
  rm -f "$output_file"

  if [[ "$status" == "FAIL" ]]; then
    failure_log="$(persist_failure_output "review-${label}" "$cmd_str" "1" "$rc" "$full_output")"
    REVIEW_VERIFY_SUMMARY+="- ${label}: ${status} (exit ${rc}, log: ${failure_log})"$'\n'
  else
    REVIEW_VERIFY_SUMMARY+="- ${label}: ${status} (exit ${rc})"$'\n'
  fi
  REVIEW_VERIFY_DETAILS+="### ${label}"$'\n'
  REVIEW_VERIFY_DETAILS+="STATUS: ${status}"$'\n'
  REVIEW_VERIFY_DETAILS+="EXIT_CODE: ${rc}"$'\n'
  REVIEW_VERIFY_DETAILS+="COMMAND: ${cmd_str}"$'\n'
  REVIEW_VERIFY_DETAILS+="OUTPUT:"$'\n'
  REVIEW_VERIFY_DETAILS+="${output}"$'\n\n'
}

run_review_verification_suite() {
  REVIEW_VERIFY_SUMMARY=""
  REVIEW_VERIFY_DETAILS=""
  REVIEW_VERIFY_ANY_FAIL=0

  run_review_command_capture "make lint" make lint
  run_review_command_capture "make typecheck" make typecheck
  run_review_command_capture "make api-rebuild (fresh backend image)" make api-rebuild
  run_review_command_capture "make test-backend" make test-backend
  run_review_command_capture "make test-frontend" make test-frontend
  run_review_command_capture "make api-smoke (runtime)" make api-smoke

  if [[ -f "$REPO_ROOT/web/playwright.config.ts" || -f "$REPO_ROOT/web/playwright.config.js" ]]; then
    run_review_command_capture "make e2e (UI smoke)" make e2e
  else
    REVIEW_VERIFY_SUMMARY+="- make e2e (UI smoke): SKIP (Playwright not configured)"$'\n'
    REVIEW_VERIFY_DETAILS+="### make e2e (UI smoke)"$'\n'
    REVIEW_VERIFY_DETAILS+="STATUS: SKIP"$'\n'
    REVIEW_VERIFY_DETAILS+="EXIT_CODE: 0"$'\n'
    REVIEW_VERIFY_DETAILS+="COMMAND: make e2e"$'\n'
    REVIEW_VERIFY_DETAILS+="OUTPUT:"$'\n'
    REVIEW_VERIFY_DETAILS+="Playwright config not found in web/."$'\n\n'
  fi

  if [[ -d "$REPO_ROOT/web/playwright-report" ]]; then
    REVIEW_VERIFY_DETAILS+="### UI Artifact Index: web/playwright-report"$'\n'
    REVIEW_VERIFY_DETAILS+="STATUS: INFO"$'\n'
    REVIEW_VERIFY_DETAILS+="OUTPUT:"$'\n'
    REVIEW_VERIFY_DETAILS+="$(find "$REPO_ROOT/web/playwright-report" -maxdepth 2 -type f | sed "s|$REPO_ROOT/||" | sed -n '1,80p')"$'\n\n'
  fi
  if [[ -d "$REPO_ROOT/web/test-results" ]]; then
    REVIEW_VERIFY_DETAILS+="### UI Artifact Index: web/test-results"$'\n'
    REVIEW_VERIFY_DETAILS+="STATUS: INFO"$'\n'
    REVIEW_VERIFY_DETAILS+="OUTPUT:"$'\n'
    REVIEW_VERIFY_DETAILS+="$(find "$REPO_ROOT/web/test-results" -maxdepth 3 -type f | sed "s|$REPO_ROOT/||" | sed -n '1,120p')"$'\n\n'
  fi
}

refresh_review_diff_filter() {
  local item
  local -a normalized=()

  REVIEW_GIT_PATHSPEC=(.)
  REVIEW_ALLOWED_AUX_FILES_DISPLAY="(none)"

  [[ -n "${ALLOWED_AUX_FILES:-}" ]] || return 0

  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    normalized+=("$item")
    REVIEW_GIT_PATHSPEC+=(":(exclude)$item")
  done < <(printf '%s\n' "$ALLOWED_AUX_FILES" | tr ',;' '\n' | awk '{$1=$1}; NF')

  if [[ "${#normalized[@]}" -gt 0 ]]; then
    REVIEW_ALLOWED_AUX_FILES_DISPLAY="$(printf '%s\n' "${normalized[@]}" | sed 's/^/- /')"
  fi
}

collect_review_diff_names() {
  refresh_review_diff_filter
  {
    git diff --name-only main...HEAD -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    git diff --cached --name-only -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    git diff --name-only -- "${REVIEW_GIT_PATHSPEC[@]}" || true
  } | awk 'NF' | sort -u
}

collect_review_diff_stat() {
  refresh_review_diff_filter
  {
    git diff --no-color --stat main...HEAD -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    git diff --cached --no-color --stat -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    git diff --no-color --stat -- "${REVIEW_GIT_PATHSPEC[@]}" || true
  } | awk 'NF'
}

collect_review_diff_patch() {
  refresh_review_diff_filter
  {
    echo "### COMMITTED_DIFF (main...HEAD)"
    git diff --no-color main...HEAD -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    echo
    echo "### STAGED_UNCOMMITTED_DIFF"
    git diff --cached --no-color -- "${REVIEW_GIT_PATHSPEC[@]}" || true
    echo
    echo "### UNSTAGED_UNCOMMITTED_DIFF"
    git diff --no-color -- "${REVIEW_GIT_PATHSPEC[@]}" || true
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

assert_no_open_mandatory_checklist_items() {
  local open_items
  open_items="$(
    awk '
      /^## Task Checklist/ {in_checklist=1; next}
      /^## / && in_checklist {exit}
      in_checklist && /^- \[ \]/ && $0 !~ /HUMAN_ONLY:/ && $0 !~ /POST_SHIP:/ {print}
    ' "$TASK_FILE"
  )"

  if [[ -n "${open_items// }" ]]; then
    die "Build blocked: mandatory task checklist items are still unfinished:
$open_items"
  fi
}

assert_no_checked_placeholder_checklist_items() {
  local placeholder_items
  placeholder_items="$(
    awk '
      /^## Task Checklist/ {in_checklist=1; next}
      /^## / && in_checklist {exit}
      in_checklist && /^- \[[xX]\]/ {
        if ($0 ~ /<required>|<todo>|<placeholder>|TODO|TBD|PENDING|<not done>/) print
      }
    ' "$TASK_FILE"
  )"

  if [[ -n "${placeholder_items// }" ]]; then
    die "Build blocked: some checked Task Checklist items still contain placeholder text:
$placeholder_items"
  fi
}

assert_required_task_sections_populated() {
  local impl verification
  impl="$(extract_markdown_section_body "Implementation Reasoning Addendum (Codex Mutable)")"
  verification="$(extract_markdown_section_body "Verification Evidence (Codex Mutable)")"

  [[ -n "${impl// }" ]] || die "Build blocked: Implementation Reasoning Addendum (Codex Mutable) is empty."
  [[ -n "${verification// }" ]] || die "Build blocked: Verification Evidence (Codex Mutable) is empty."
}

assert_no_unfinished_markers_in_scope() {
  local changed path
  changed="$(collect_current_changed_paths)"

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    [[ -f "$path" ]] || continue

    if grep -nE 'TODO|FIXME|XXX|NOT_IMPLEMENTED|stubbed|placeholder|throw new Error\("TODO' "$path" >/dev/null 2>&1; then
      die "Unfinished implementation markers found in changed file: $path"
    fi
  done <<<"$changed"
}

assert_basic_build_sanity() {
  local changed py_errors=""
  changed="$(collect_current_changed_paths)"
  [[ -n "${changed// }" ]] || die "Post-build sanity: no files were modified."

  while IFS= read -r f; do
    [[ "$f" == *.py ]] || continue
    [[ -f "$f" ]] || continue
    if ! python3 -m py_compile "$f" 2>/dev/null; then
      py_errors+="$f"$'\n'
    fi
  done <<<"$changed"

  if [[ -n "${py_errors// }" ]]; then
    die "Post-build sanity: Python syntax errors detected in:
$py_errors"
  fi
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
   - Human Rework Input (Mutable)
   - Retry Log (Max 3)
   - Automation Log (Mutable)
2) Keep marker exactly: <!-- IMMUTABLE_PLAN_END -->
3) Keep output deterministic and scoped to requested feature.
4) Do not edit files directly; only return final markdown content between markers.
5) The Task Checklist must contain only actionable implementation items. Mark reviewer-only or post-ship items with HUMAN_ONLY: or POST_SHIP: prefixes.
6) Do not include tool logs or transcripts inside the marked output.

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
  require_tool copilot
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

  assert_human_approval_gate_passed

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
4) Complete all mandatory Task Checklist items. Do not leave unfinished mandatory items unchecked.
5) Do not mark checklist items complete unless the implementation is actually finished.
6) Write concrete evidence into Verification Evidence (commands run, results, key artifacts).
7) Run required checks:
   - make lint
   - make typecheck
   - make api-rebuild
   - make test-backend
   - make test-frontend
   - make api-smoke
   - make e2e only if Playwright exists
8) Verification retry policy is deterministic:
   - first failure: rerun once unchanged
   - if still failing: one scoped auto-fix cycle
   - stop after that and log blocker
EOF
)"

  run_with_retries "Builder implementation pass" run_builder_prompt "$prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed by implementation pass."
    die "Immutable approved plan content changed in $TASK_FILE."
  fi

  assert_basic_build_sanity
  run_verification_suite
  assert_no_open_mandatory_checklist_items
  assert_no_checked_placeholder_checklist_items
  assert_required_task_sections_populated
  assert_no_unfinished_markers_in_scope

  append_task_block "Build Result" "Implementation, sanity checks, and verification suite completed successfully."
  stage_scoped_changes "build" "1"
  log "Auto-staged scoped build outputs for review."
}

run_sonnet_review() {
  local diff_stat diff_names diff_patch task_content prompt
  refresh_review_diff_filter
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

Deterministic verification rerun summary:
$REVIEW_VERIFY_SUMMARY

Deterministic verification rerun details:
$REVIEW_VERIFY_DETAILS

Approved auxiliary files allowlist:
$REVIEW_ALLOWED_AUX_FILES_DISPLAY

Allowlist rule:
- Treat allowlisted files as explicitly approved auxiliary workflow/config changes.
- Do not raise out-of-scope findings solely because allowlisted files changed.

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
If any deterministic verification command failed, STATUS must be NEEDS_FIXES.
EOF
)"
  run_copilot_prompt_with_cache "review" "$REVIEW_MODEL" "$prompt" "$task_content"
}

run_opus_escalation_review() {
  local sonnet_output="$1"
  local diff_patch task_content prompt
  refresh_review_diff_filter
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

Deterministic verification rerun summary:
$REVIEW_VERIFY_SUMMARY

Deterministic verification rerun details:
$REVIEW_VERIFY_DETAILS

Approved auxiliary files allowlist:
$REVIEW_ALLOWED_AUX_FILES_DISPLAY

Allowlist rule:
- Treat allowlisted files as explicitly approved auxiliary workflow/config changes.
- Do not raise out-of-scope findings solely because allowlisted files changed.

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

  local previous_review_id
  previous_review_id="$(latest_review_id || true)"
  if [[ -n "$previous_review_id" ]] && review_status_exists "$previous_review_id" "Implemented"; then
    validate_rework_analysis_and_matrix "$previous_review_id"
  fi

  local review_id sonnet_output sonnet_status sonnet_risk
  review_id="$(next_review_id)"
  run_review_verification_suite
  append_task_block "Review Cycle ${review_id} - Verification Rerun" "$REVIEW_VERIFY_SUMMARY"
  sonnet_output="$(run_sonnet_review 2>&1 | tee /dev/stderr)"
  sonnet_status="$(parse_status "$sonnet_output")"
  sonnet_risk="$(parse_risk "$sonnet_output")"

  if [[ "$REVIEW_VERIFY_ANY_FAIL" -eq 1 && "$sonnet_status" == "APPROVED" ]]; then
    sonnet_output="$(printf '%s\n\nSYSTEM_NOTE:\n- Deterministic verification rerun had failures; overriding STATUS to NEEDS_FIXES.' "$sonnet_output")"
    sonnet_status="NEEDS_FIXES"
    sonnet_risk="${sonnet_risk:-MEDIUM}"
  fi

  append_task_block "Review Cycle ${review_id} - Sonnet (${REVIEW_MODEL})" "$sonnet_output"
  append_review_status "$review_id" "Reviewed" "$sonnet_status" "${sonnet_risk:-UNKNOWN}"

  if review_needs_escalation "$sonnet_status" "$sonnet_risk" "$sonnet_output"; then
    local opus_output opus_status opus_risk
    opus_output="$(run_opus_escalation_review "$sonnet_output" 2>&1 | tee /dev/stderr)"
    opus_status="$(parse_status "$opus_output")"
    opus_risk="$(parse_risk "$opus_output")"
    append_task_block "Review Cycle ${review_id} - Opus Escalation (${REVIEW_ESCALATION_MODEL})" "$opus_output"
    append_review_status "$review_id" "Reviewed" "$opus_status" "${opus_risk:-UNKNOWN}"
    if [[ "$opus_status" == "APPROVED" ]]; then
      return 0
    fi
    append_review_human_input_placeholder "$review_id"
    return 2
  fi

  if [[ "$sonnet_status" == "APPROVED" ]]; then
    return 0
  fi

  append_review_human_input_placeholder "$review_id"
  return 2
}

cmd_rework() {
  require_tool copilot
  validate_task_file "$1"
  [[ -f "$TASK_FILE" ]] || die "Task file not found: $TASK_FILE"

  local review_id review_context latest_result immutable_before immutable_after parsed_status parsed_risk
  local human_input analysis_prompt implementation_prompt analysis_summary matrix_summary analysis_snapshot
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

  ensure_rework_human_input_block_ready "$review_id"
  human_input="$(extract_latest_named_text_block "Review Cycle ${review_id} - Human Input")"
  [[ -n "$human_input" ]] || die "Could not extract structured human input for ${review_id}."

  immutable_before="$(immutable_hash)"
  analysis_prompt="$(cat <<EOF
Analysis pass for latest review cycle ${review_id} in $TASK_FILE.

Latest review context:
$review_context

Structured human input:
$human_input

Hard constraints:
1) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
2) This is analysis only. Do NOT implement code changes in this pass.
3) Update/create exactly these blocks in $TASK_FILE as markdown headings with \`\`\`text fenced bodies:
   - Review Cycle ${review_id} - Rework Analysis
   - Review Cycle ${review_id} - Rework Answer Matrix
4) Fill Rework Analysis with required one-line fields:
   ROOT_CAUSE:
   FINDINGS_ADDRESSED:
   PLANNED_CHANGES:
   VALIDATION_PLAN:
   UNRESOLVED_ASSUMPTIONS:
5) Fill Rework Answer Matrix with one ENTRY per unresolved reviewer finding and human comment.
   Each entry must include one-line fields:
   REVIEWER_FINDING:
   HUMAN_COMMENT:
   ROOT_CAUSE:
   CHANGE_MADE:
   VERIFICATION_PERFORMED:
   STATUS:
6) STATUS values in this analysis pass must be one of:
   PLANNED | NEEDS_INPUT | BLOCKED
7) Do not run make commands in this pass.
8) Use the exact field labels shown above. Do not rename them.
EOF
)"

  run_with_retries "Builder rework analysis pass (${review_id})" run_builder_prompt "$analysis_prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed during rework for ${review_id}."
    die "Immutable approved plan content changed during rework."
  fi

  validate_rework_analysis_and_matrix "$review_id"

  analysis_summary="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Analysis")"
  matrix_summary="$(extract_latest_named_text_block "Review Cycle ${review_id} - Rework Answer Matrix")"

  [[ -n "$analysis_summary" ]] || die "Failed to capture validated Rework Analysis block for ${review_id}."
  analysis_snapshot="$analysis_summary"

  immutable_before="$(immutable_hash)"
  implementation_prompt="$(cat <<EOF
Implementation pass for latest review cycle ${review_id} in $TASK_FILE.

Latest review context:
$review_context

Structured human input:
$human_input

Approved analysis plan:
$analysis_summary

Answer matrix to complete:
$matrix_summary

Hard constraints:
1) Do not modify content above <!-- IMMUTABLE_PLAN_END --> in $TASK_FILE.
2) Implement only findings/test gaps from latest review cycle (${review_id}) and structured human input.
3) Keep changes minimal and in-scope with acceptance criteria.
4) Do not redo completed work or broad refactors.
5) Complete all mandatory checklist items that remain open for this rework scope.
6) Update mutable sections in $TASK_FILE with implementation reasoning and verification evidence.
7) Update Review Cycle ${review_id} - Rework Answer Matrix (keep heading + \`\`\`text fenced body):
   - Keep same entries.
   - Fill CHANGE_MADE and VERIFICATION_PERFORMED with what was actually done.
   - Set STATUS to one of: RESOLVED | PARTIAL | BLOCKED.
8) Run verification:
   - make lint
   - make typecheck
   - make api-rebuild
   - make test-backend
   - make test-frontend
   - make api-smoke
   - make e2e only if Playwright exists
9) Do NOT modify Review Cycle ${review_id} - Rework Analysis. Preserve it exactly as provided.
10) Do NOT rename any field labels in Review Cycle ${review_id} - Rework Answer Matrix.
EOF
)"

  run_with_retries "Builder rework implementation pass (${review_id})" run_builder_prompt "$implementation_prompt"
  immutable_after="$(immutable_hash)"
  if [[ "$immutable_before" != "$immutable_after" ]]; then
    append_retry_log "Plan integrity violation: immutable section changed during rework implementation for ${review_id}."
    die "Immutable approved plan content changed during rework implementation."
  fi

  replace_latest_named_text_block "Review Cycle ${review_id} - Rework Analysis" "$analysis_snapshot"

  validate_rework_analysis_and_matrix "$review_id"

  assert_basic_build_sanity
  run_verification_suite
  assert_required_task_sections_populated
  assert_no_unfinished_markers_in_scope
  append_review_status "$review_id" "Implemented" "NEEDS_REVIEW" "PENDING"
  append_task_block "Review Cycle ${review_id} - Rework Result" "Two-pass rework completed (analysis -> implementation) for latest review findings."
  stage_scoped_changes "rework" "1"
  log "Auto-staged scoped rework outputs for review."
}

cmd_ship() {
  require_tool git
  require_tool gh
  validate_task_file "$1"

  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  [[ "$current_branch" != "main" ]] || die "Refusing to ship from main branch."

  if has_unstaged_or_untracked_changes; then
    die "Ship requires a fully staged snapshot with no unstaged/untracked files. Run task-review after scoped staging."
  fi
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
      --body "Automated by task_flow.sh with Copilot plan, Copilot builder, Sonnet review, and escalation-on-risk." 2>&1)"
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
  cmd_build "$task"

  local review_attempt rc
  for ((review_attempt=1; review_attempt<=MAX_RETRIES; review_attempt++)); do
    log "Review cycle attempt $review_attempt/$MAX_RETRIES"
    stage_scoped_changes "all/review-attempt-$review_attempt" "1"
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
    review-input) cmd_review_input "$task" ;;
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
from orchestration.models.build import BuildOutput, RetryEntry
from orchestration.models.pipeline import PipelineState
from orchestration.services.scope import derive_verification_support_paths


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def build_build_prompt(
    state: PipelineState,
    *,
    prior_build_output: BuildOutput | None = None,
    prior_retry_entries: list[RetryEntry] | None = None,
    prior_blockers: list[str] | None = None,
) -> str:
    planned_paths = state.plan_output.allowed_paths() if state.plan_output else []
    verification_support_paths = derive_verification_support_paths(planned_paths)
    prior_retry_entries = prior_retry_entries or []
    prior_blockers = prior_blockers or []
    return f"""
    You are the builder.

Implement the approved task in the repository before you respond.

Return strict JSON only.

Required JSON shape:
{{
  "summary": "string",
  "changed_files": ["path"],
  "extra_changed_files": [{{"path":"path","reason":"string","reason_source":"builder"}}],
  "completed_checklist_item_ids": ["CHK-1"],
  "implementation_notes": ["string"]
}}

Task: {state.issue.task_file}
Repo root: {state.issue.repo_root}
Plan summary: {state.plan_output.summary if state.plan_output else ""}
Acceptance criteria:
{chr(10).join(f"- {x}" for x in (state.plan_output.acceptance_criteria if state.plan_output else []))}
Planned paths:
{chr(10).join(f"- {x}" for x in planned_paths)}

Verification support paths:
{chr(10).join(f"- {x}" for x in verification_support_paths)}

Checklist:
{chr(10).join(f"- {item.id}: {item.text}" for item in (state.plan_output.checklist if state.plan_output else []))}

Previous blocked-build context:
- previous_build_summary: {prior_build_output.summary if prior_build_output else "None"}
- previous_changed_files:
{_bullets(prior_build_output.changed_files if prior_build_output else [])}
- previous_build_blockers:
{_bullets(prior_blockers)}
- previous_retry_history:
{_bullets([
    f"{entry.label}: attempt {entry.attempt}/{entry.max_attempts}, signature={entry.failure_signature or 'n/a'}, notes={entry.notes}"
    for entry in prior_retry_entries
])}

Hard constraints:
1) Actually edit the repository files needed for this task before returning.
2) Keep changes scoped to the task acceptance criteria, planned paths, and verification support paths.
3) Run the required verification commands needed to support your summary.
4) Do not claim filesystem write restrictions unless a real tool invocation fails and you include the concrete failed command in implementation_notes.
5) Return changed_files based on files you actually modified for this task.
6) If you changed any file outside the planned paths and verification support paths, include it in extra_changed_files with your best explanation of why it changed.
7) If you cannot infer why an out-of-scope file changed, say so explicitly in the reason field.
8) If you are rerunning build after an earlier blocked attempt, incorporate the prior failure history above and change your approach instead of repeating the same fix strategy.
    """.strip()


def build_retry_request_prompt(
    state: PipelineState,
    *,
    build_output: BuildOutput,
    blockers: list[str],
    retries: list[RetryEntry],
) -> str:
    return f"""
You are the builder deciding whether more retries would materially help.

Return strict JSON only.

Required JSON shape:
{{
  "summary": "string",
  "why_more_retries_help": "string",
  "proposed_new_strategy": "string",
  "latest_failures": ["string"],
  "requested_retry_count": 0,
  "valid_reason": false
}}

Task: {state.issue.task_file}
Plan summary: {state.plan_output.summary if state.plan_output else ""}
Build summary: {build_output.summary}

Current blockers:
{_bullets(blockers)}

Retry history:
{_bullets([
    f"{entry.label}: attempt {entry.attempt}/{entry.max_attempts}, signature={entry.failure_signature or 'n/a'}, notes={entry.notes}"
    for entry in retries
])}

Latest verification summary:
{build_output.verification.summary if build_output.verification else "None"}

Rules:
1) Set `valid_reason` to true only if you can name a concrete new strategy that was not already exhausted by the retry history.
2) If `valid_reason` is true, set `requested_retry_count` to the minimum additional retries that would be useful.
3) If the failure appears stuck, repetitive, ambiguous, or under-specified, set `valid_reason` to false and ask for human guidance instead of more retries.
4) Keep `latest_failures` concrete and based on the actual retry history and blockers above.
""".strip()

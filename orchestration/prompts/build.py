from orchestration.models.pipeline import PipelineState


def build_build_prompt(state: PipelineState) -> str:
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
{chr(10).join(f"- {x}" for x in (state.plan_output.allowed_paths() if state.plan_output else []))}

Checklist:
{chr(10).join(f"- {item.id}: {item.text}" for item in (state.plan_output.checklist if state.plan_output else []))}

Hard constraints:
1) Actually edit the repository files needed for this task before returning.
2) Keep changes scoped to the task acceptance criteria and planned paths.
3) Run the required verification commands needed to support your summary.
4) Do not claim filesystem write restrictions unless a real tool invocation fails and you include the concrete failed command in implementation_notes.
5) Return changed_files based on files you actually modified for this task.
6) If you changed any file outside the planned paths, include it in extra_changed_files with your best explanation of why it changed.
7) If you cannot infer why an out-of-scope file changed, say so explicitly in the reason field.
""".strip()

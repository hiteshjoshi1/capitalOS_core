from orchestration.models.pipeline import PipelineState


def build_build_prompt(state: PipelineState) -> str:
    return f"""
You are the builder.

Return strict JSON only.

Required JSON shape:
{{
  "summary": "string",
  "changed_files": ["path"],
  "completed_checklist_item_ids": ["CHK-1"],
  "implementation_notes": ["string"]
}}

Task: {state.issue.task_file}
Plan summary: {state.plan_output.summary if state.plan_output else ""}
Acceptance criteria:
{chr(10).join(f"- {x}" for x in (state.plan_output.acceptance_criteria if state.plan_output else []))}
""".strip()
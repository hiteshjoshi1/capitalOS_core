from orchestration.models.pipeline import PipelineState


def build_rework_analysis_prompt(state: PipelineState) -> str:
    cycle = state.get_active_review_cycle()
    return f"""
You are doing rework analysis.

Return strict JSON only.

Required JSON shape:
{{
  "rework_cycle_id": "W1",
  "review_id": "{cycle.review_id if cycle else ''}",
  "root_cause": "string",
  "findings_addressed": ["string"],
  "planned_changes": ["string"],
  "validation_plan": ["string"],
  "unresolved_assumptions": ["string"],
  "answer_matrix": [
    {{
      "reviewer_finding": "string",
      "human_comment": "string",
      "root_cause": "string",
      "change_made": "",
      "verification_performed": "",
      "status": "planned"
    }}
  ]
}}
""".strip()


def build_rework_implementation_prompt(state: PipelineState) -> str:
    rework = state.get_active_rework_cycle()
    analysis = rework.analysis if rework else None
    return f"""
You are implementing a rework.

Return strict JSON only.

Required JSON shape:
{{
  "rework_cycle_id": "{rework.rework_cycle_id if rework else ''}",
  "review_id": "{rework.source_review_id if rework else ''}",
  "summary": "string",
  "changed_files": ["path"],
  "verification_summary": "string",
  "completed": true
}}

Planned changes:
{chr(10).join(f"- {x}" for x in (analysis.planned_changes if analysis else []))}
""".strip()
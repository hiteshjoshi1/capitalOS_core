def build_plan_prompt(task_markdown: str) -> str:
    return f"""
You are the planner.

Return strict JSON only.

Required JSON shape:
{{
  "summary": "string",
  "architecture_decisions": ["string"],
  "risks": ["string"],
  "open_questions": ["string"],
  "acceptance_criteria": ["string"],
  "planned_paths": ["relative/path"],
  "checklist": [
    {{
      "id": "CHK-1",
      "text": "string",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["relative/path"]
    }}
  ]
}}

Rules:
1) planned_paths must be concrete repo-relative paths or directories.
2) Use directory paths when multiple files under the same area are expected.
3) Keep scope narrow.
4) Do not use markdown as machine state.

Task markdown:
{task_markdown}
""".strip()
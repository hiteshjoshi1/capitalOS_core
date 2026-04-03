from __future__ import annotations

from orchestration.models.pipeline import PipelineState
from orchestration.services.task_markdown import TaskMarkdownService


def build_agent_run_prompt(state: PipelineState) -> str:
    markdown_service = TaskMarkdownService(state.issue.repo_root)
    task_markdown = markdown_service.read(state.issue.task_file)

    previous_errors = state.errors[-5:]
    previous_blockers = state.blockers[-5:]

    return f"""
You are the single-session implementation agent for this task.

Your responsibilities in this session:
1) Derive a concrete implementation plan from the task markdown.
2) Implement the code changes in the repository.
3) Verify semantic intent against acceptance criteria.
4) Return strict JSON only.

Task file: {state.issue.task_file}
Repo root: {state.issue.repo_root}

Task markdown:
{task_markdown}

Recent failure context (if any):
- blockers:
{chr(10).join(f"  - {item}" for item in previous_blockers) if previous_blockers else "  - None"}
- errors:
{chr(10).join(f"  - {item}" for item in previous_errors) if previous_errors else "  - None"}

Return JSON matching exactly this shape:
{{
  "summary": "string",
  "plan_summary": "string",
  "architecture_decisions": ["string"],
  "risks": ["string"],
  "open_questions": ["string"],
  "acceptance_criteria": ["string"],
  "planned_paths": ["path-or-directory"],
  "checklist": [
    {{
      "id": "CHK-1",
      "text": "string",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["path-or-directory"]
    }}
  ],
  "changed_files": ["path"],
  "extra_changed_files": [
    {{
      "path": "path",
      "reason": "why this out-of-scope file change was necessary",
      "reason_source": "builder"
    }}
  ],
  "implementation_notes": ["string"],
  "acceptance_criteria_checks": [
    {{
      "criterion": "string",
      "status": "pass|partial|fail",
      "evidence": "string"
    }}
  ],
  "semantic_intent_achieved": true,
  "risk_flags": ["string"]
}}

Rules:
1) Perform repository edits before returning.
2) Keep changes minimal and aligned to acceptance criteria.
3) Every changed file must be real and currently changed in git status.
4) Any changed file outside planned paths must be included in extra_changed_files with a concrete reason.
5) Do not include markdown fences or prose outside JSON.
6) If semantic intent is not achieved, set semantic_intent_achieved=false and explain exactly why in checks/evidence.
""".strip()

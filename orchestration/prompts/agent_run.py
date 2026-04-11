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
  "verification_commands_run": [
    {{
      "command": "make test-backend",
      "status": "pass|fail|skip",
      "evidence": "string"
    }}
  ],
  "unresolved_failures": ["string"],
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
5) In this single session you must do the full loop: understand task, derive plan, implement, add/update relevant tests, run relevant tests, fix failures, rerun until green or truly stuck.
6) Relevant test policy:
   - if you changed `api/` or `migrations/`, run exactly these backend verification commands: `make api-rebuild`, `make contract-backend`, `make test-backend`, `make api-smoke`
   - if you changed `web/`, run exactly these frontend verification commands: `make lint`, `make typecheck`, `make contract-frontend`, `make test-frontend`, `make e2e` when Playwright exists
   - if you changed `orchestration/`, workflow docs, or the `Makefile`, run exactly this pipeline verification command: `make orch-test`
   - if you changed multiple areas, run the union of the exact `make ...` commands above
   - do not substitute equivalent raw commands like `docker compose ...`, `pytest`, `npm test`, or `npm run build` when a required `make ...` target exists
   - record the exact command strings you ran in `verification_commands_run`; they must match the executed `make ...` commands
7) Do not commit, push, or open a PR in this session. Ship owns commits.
8) Record every relevant test command you ran in verification_commands_run.
9) If semantic intent is achieved, unresolved_failures must be empty.
10) Do not include markdown fences or prose outside JSON.
11) If semantic intent is not achieved, set semantic_intent_achieved=false and explain exactly why in checks/evidence.
""".strip()

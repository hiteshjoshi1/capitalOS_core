from __future__ import annotations

from orchestration.models.build import BuildOutput
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.git import GitService
from orchestration.services.llm import LLMService
from orchestration.services.verification import VerificationService
from orchestration.prompts.build import build_build_prompt
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _builder_fix_callback(name: str, command: str, exit_code: int, output: str) -> None:
    # Intentionally thin in Part 2.
    # In Part 3 you can replace this with a real builder autopilot fix invocation.
    # Keeping it as a hook prevents retry logic from being embedded in nodes.
    return None


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "build"
    pipeline.workflow_status = "running"

    cfg = get_config()
    decision = pipeline.human_gate_decisions.get("plan_approval")
    if not decision or decision.decision != "approved":
        raise RuntimeError("Build blocked: plan approval gate has not approved the plan.")

    builder = LLMService(model=cfg.builder_model)
    build_output = builder.complete_structured(build_build_prompt(pipeline), BuildOutput)
    build_output.builder_model = cfg.builder_model

    verification_service = VerificationService(pipeline.issue.repo_root)
    verification, retries = verification_service.run_default_suite(
        max_attempts=cfg.max_retries,
        on_code_retry_fix=_builder_fix_callback,
    )
    build_output.verification = verification

    git = GitService(pipeline.issue.repo_root)
    build_output.changed_files = git.changed_files()
    pipeline.build_output = build_output

    for entry in retries:
        pipeline.add_retry(entry)

    allowed = {pipeline.issue.task_file, *cfg.allowed_aux_files}
    allowed.update(build_output.changed_files)
    staged, blocked = git.stage_scoped_changes(allowed)

    if blocked:
        pipeline.blockers.append(
            f"Out-of-scope changed files detected during build: {', '.join(blocked)}"
        )

    if verification.any_failures:
        pipeline.blockers.append("Verification suite failed during build.")
        pipeline.workflow_status = "blocked"

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
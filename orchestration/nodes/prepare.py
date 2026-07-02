from __future__ import annotations

from pathlib import Path

from orchestration.models.pipeline import PrepareResult
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.task_markdown import TaskMarkdownService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "prepare"
    pipeline.workflow_status = "running"
    emit_stage_start(
        "prepare",
        current_action="Preparing task file and feature branch",
        evidence=[f"task_file={pipeline.issue.task_file}", f"branch={pipeline.issue.branch}"],
    )

    cfg = get_config()
    git = GitService(pipeline.issue.repo_root)
    md = TaskMarkdownService(pipeline.issue.repo_root)

    task_path = Path(pipeline.issue.repo_root) / pipeline.issue.task_file
    if not task_path.exists():
        raise RuntimeError(
            f"Task file does not exist: {pipeline.issue.task_file}. "
            "Create the task file explicitly before running the workflow."
        )
    md.ensure_required_markers(pipeline.issue.task_file)
    emit_progress("prepare", current_action="Task file verified", actions_taken=[f"Verified `{pipeline.issue.task_file}` exists"])
    git.ensure_clean_worktree_except([pipeline.issue.task_file])
    git.checkout_main_and_prepare_branch(pipeline.issue.branch, base_branch=cfg.base_branch)

    pipeline.prepare_result = PrepareResult(
        base_branch=cfg.base_branch,
        branch_name=pipeline.issue.branch,
        branch_ready=True,
        task_file_bootstrapped=False,
        summary=f"Checked out `{pipeline.issue.branch}` from `{cfg.base_branch}` and verified task file exists.",
    )

    render_task_file(pipeline)
    emit_stage_end(
        "prepare",
        status="completed",
        evidence=[f"base_branch={cfg.base_branch}", f"branch={pipeline.issue.branch}"],
        conclusion="Prepare stage completed and the feature branch is ready.",
    )
    return dump_pipeline_state(pipeline)

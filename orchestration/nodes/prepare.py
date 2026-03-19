from __future__ import annotations

from orchestration.models.pipeline import PrepareResult
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.git import GitService
from orchestration.services.task_markdown import TaskMarkdownService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "prepare"
    pipeline.workflow_status = "running"

    cfg = get_config()
    git = GitService(pipeline.issue.repo_root)
    md = TaskMarkdownService(pipeline.issue.repo_root)

    md.bootstrap_if_missing(
        pipeline.issue.task_file,
        pipeline.issue.title,
        pipeline.issue.issue_id,
    )
    git.ensure_clean_worktree_except([pipeline.issue.task_file])
    git.checkout_main_and_prepare_branch(pipeline.issue.branch, base_branch=cfg.base_branch)

    pipeline.prepare_result = PrepareResult(
        base_branch=cfg.base_branch,
        branch_name=pipeline.issue.branch,
        branch_ready=True,
        task_file_bootstrapped=True,
        summary=f"Checked out `{pipeline.issue.branch}` from `{cfg.base_branch}` and ensured task file exists.",
    )

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
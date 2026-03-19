from __future__ import annotations

from orchestration.models.ship import ShipResult
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.git import GitService
from orchestration.services.github import GitHubService
from orchestration.services.integrity import IntegrityService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "ship"
    pipeline.workflow_status = "running"

    cfg = get_config()
    IntegrityService(pipeline.issue.repo_root).assert_matches_planned_hash(pipeline)

    cycle = pipeline.get_active_review_cycle()
    if not cycle or cycle.status != "approved":
        raise RuntimeError("Ship blocked: latest review cycle is not fully approved.")

    if pipeline.blockers:
        raise RuntimeError(
            f"Ship blocked: unresolved blockers remain: {', '.join(pipeline.blockers)}"
        )

    if pipeline.build_output is None:
        raise RuntimeError("Ship blocked: no build output recorded.")

    if pipeline.build_output.verification is None:
        raise RuntimeError("Ship blocked: no verification evidence recorded.")

    if pipeline.build_output.verification.any_failures:
        raise RuntimeError("Ship blocked: verification failures remain in build output.")

    git = GitService(pipeline.issue.repo_root)
    if git.current_branch() == cfg.base_branch:
        raise RuntimeError(f"Refusing to ship from base branch `{cfg.base_branch}`.")

    git.add(pipeline.issue.task_file)
    committed = git.commit_if_needed(
        f"feat: complete issue #{pipeline.issue.issue_id} workflow execution"
    )
    git.push(pipeline.issue.branch)

    pr_created = False
    pr_url = None
    summary = f"Pushed branch `{pipeline.issue.branch}`."

    if cfg.create_pr_on_ship:
        gh = GitHubService(pipeline.issue.repo_root)
        pr = gh.create_pr(
            branch=pipeline.issue.branch,
            base=cfg.base_branch,
            title=f"Issue #{pipeline.issue.issue_id}: {pipeline.issue.slug}",
            body="Automated by LangGraph orchestration pipeline.",
        )
        pr_created = pr.created
        pr_url = pr.url
        summary += f" {pr.message}"

    pipeline.ship_result = ShipResult(
        committed=committed,
        pushed=True,
        pr_created=pr_created,
        pr_url=pr_url,
        summary=summary,
    )
    pipeline.workflow_status = "shipped"
    pipeline.current_stage = "done"

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
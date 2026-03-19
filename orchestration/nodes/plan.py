from __future__ import annotations

from orchestration.models.plan import PlanOutput
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.llm import LLMService
from orchestration.services.task_markdown import TaskMarkdownService
from orchestration.prompts.plan import build_plan_prompt
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "plan"
    pipeline.workflow_status = "running"

    cfg = get_config()
    md = TaskMarkdownService(pipeline.issue.repo_root)
    md.ensure_required_markers(pipeline.issue.task_file)
    task_markdown = md.read(pipeline.issue.task_file)

    planner = LLMService(model=cfg.planner_model)
    plan = planner.complete_structured(build_plan_prompt(task_markdown), PlanOutput)
    plan.planner_model = cfg.planner_model
    plan.immutable_plan_hash = md.immutable_hash(task_markdown)

    pipeline.plan_output = plan
    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
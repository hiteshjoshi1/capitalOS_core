from __future__ import annotations

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.llm import LLMService
from orchestration.services.task_markdown import TaskMarkdownService
from orchestration.prompts.plan import build_plan_prompt
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.PLAN
    pipeline.workflow_status = "running"
    emit_stage_start(
        PipelineStage.PLAN,
        current_action="Generating implementation plan from task markdown",
        evidence=[f"task_file={pipeline.issue.task_file}"],
    )

    cfg = get_config()
    md = TaskMarkdownService(pipeline.issue.repo_root)
    md.ensure_required_markers(pipeline.issue.task_file)
    task_markdown = md.read(pipeline.issue.task_file)
    emit_progress(
        PipelineStage.PLAN,
        current_action="Task markdown loaded",
        evidence=[f"characters={len(task_markdown)}"],
        reasoning="The immutable plan section is used as input for structured planning.",
    )

    planner = LLMService(PipelineStage.PLAN)
    plan = planner.complete_structured(build_plan_prompt(task_markdown), PlanOutput)
    plan.planner_model = cfg.planner_model
    plan.immutable_plan_hash = md.immutable_hash(task_markdown)

    pipeline.plan_output = plan
    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.PLAN,
        status="completed",
        evidence=[f"planned_paths={len(plan.planned_paths)}", f"checklist_items={len(plan.checklist)}"],
        conclusion="Plan generated and written to the task file.",
    )
    return dump_pipeline_state(pipeline)

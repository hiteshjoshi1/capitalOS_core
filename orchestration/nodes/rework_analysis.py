from __future__ import annotations

from orchestration.models.rework import ReworkAnalysis, ReworkCycle
from orchestration.models.stage import PipelineStage
from orchestration.models.stage import PipelineStage
from orchestration.prompts.rework import build_rework_analysis_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.integrity import IntegrityService
from orchestration.services.llm import LLMService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.REWORK_ANALYSIS
    pipeline.workflow_status = "running"

    IntegrityService(pipeline.issue.repo_root).assert_matches_planned_hash(pipeline)

    review_cycle = pipeline.get_active_review_cycle()
    if not review_cycle:
        raise RuntimeError("Cannot start rework analysis without an active review cycle.")

    cfg = get_config()
    rework_id = pipeline.next_rework_id()
    analyst = LLMService(PipelineStage.REWORK_ANALYSIS)
    analysis = analyst.complete_structured(build_rework_analysis_prompt(pipeline), ReworkAnalysis)
    analysis.rework_cycle_id = rework_id
    analysis.review_id = review_cycle.review_id

    cycle = ReworkCycle(
        rework_cycle_id=rework_id,
        source_review_id=review_cycle.review_id,
        analysis=analysis,
        status="analysis_complete",
    )

    pipeline.rework_cycles.append(cycle)
    pipeline.active_rework_cycle_id = rework_id

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
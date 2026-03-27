from __future__ import annotations

import hashlib
import json

from orchestration.models.rework import ReworkAnalysis, ReworkCycle
from orchestration.models.stage import PipelineStage
from orchestration.prompts.rework import build_rework_analysis_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.integrity import IntegrityService
from orchestration.services.llm import LLMService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _rework_analysis_input_fingerprint(pipeline, review_cycle, source_review_cycle) -> str:
    payload = {
        "active_review_id": review_cycle.review_id,
        "source_review_id": source_review_cycle.review_id,
        "source_review": source_review_cycle.model_dump(mode="json"),
        "semantic_requirements": pipeline.get_semantic_requirements(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.REWORK_ANALYSIS
    pipeline.workflow_status = "running"

    IntegrityService(pipeline.issue.repo_root).assert_matches_planned_hash(pipeline)

    review_cycle = pipeline.get_active_review_cycle()
    if not review_cycle:
        raise RuntimeError("Cannot start rework analysis without an active review cycle.")
    source_review_cycle = pipeline.get_rework_context_review_cycle()
    if not source_review_cycle:
        raise RuntimeError("Cannot determine substantive review context for rework analysis.")
    input_fingerprint = _rework_analysis_input_fingerprint(
        pipeline,
        review_cycle,
        source_review_cycle,
    )
    existing_rework = pipeline.get_active_rework_cycle()
    if (
        existing_rework
        and existing_rework.input_fingerprint == input_fingerprint
        and existing_rework.analysis is not None
        and existing_rework.implementation is None
    ):
        emit_progress(
            PipelineStage.REWORK_ANALYSIS,
            current_action="Reusing existing rework analysis for identical inputs",
            evidence=[f"rework_id={existing_rework.rework_cycle_id}"],
            reasoning="The stage re-entered without any substantive review change, so the prior analysis is reused.",
        )
        return dump_pipeline_state(pipeline)

    cfg = get_config()
    rework_id = pipeline.next_rework_id()
    effective_review = source_review_cycle.escalation_review or source_review_cycle.agent_review
    emit_stage_start(
        PipelineStage.REWORK_ANALYSIS,
        current_action="Analyzing review findings for the next rework cycle",
        evidence=[
            f"active_review_id={review_cycle.review_id}",
            f"source_review_id={source_review_cycle.review_id}",
            f"rework_id={rework_id}",
            f"findings={len(effective_review.findings) if effective_review else 0}",
            f"existing_reworks={len(pipeline.rework_cycles)}",
            f"max_reworks={cfg.max_rework_cycles}",
        ],
    )
    analyst = LLMService(PipelineStage.REWORK_ANALYSIS)
    emit_progress(
        PipelineStage.REWORK_ANALYSIS,
        current_action="Requesting rework analysis from model",
        evidence=[
            f"active_review_id={review_cycle.review_id}",
            f"source_review_id={source_review_cycle.review_id}",
            f"model={cfg.builder_model}",
        ],
        reasoning="The rework plan should translate review findings into concrete implementation steps and validation.",
    )
    analysis = analyst.complete_structured(build_rework_analysis_prompt(pipeline), ReworkAnalysis)
    analysis.rework_cycle_id = rework_id
    analysis.review_id = source_review_cycle.review_id

    cycle = ReworkCycle(
        rework_cycle_id=rework_id,
        source_review_id=source_review_cycle.review_id,
        input_fingerprint=input_fingerprint,
        analysis=analysis,
        status="analysis_complete",
    )

    pipeline.rework_cycles.append(cycle)
    pipeline.active_rework_cycle_id = rework_id

    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.REWORK_ANALYSIS,
        status="completed",
        evidence=[f"rework_id={rework_id}", f"planned_changes={len(analysis.planned_changes)}", f"validation_steps={len(analysis.validation_plan)}"],
        conclusion=analysis.root_cause,
    )
    return dump_pipeline_state(pipeline)

from __future__ import annotations

from orchestration.models.review import AgentReview, ReviewCycle
from orchestration.models.stage import PipelineStage
from orchestration.prompts.review import build_review_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start, emit_waiting_for_human
from orchestration.services.git import GitService
from orchestration.services.llm import LLMService
from orchestration.services.scope import ScopePolicyService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.AGENT_REVIEW
    pipeline.workflow_status = "running"

    cfg = get_config()
    review_id = pipeline.next_review_id()
    source = "rework" if pipeline.active_rework_cycle_id else "build"
    emit_stage_start(
        PipelineStage.AGENT_REVIEW,
        current_action="Reviewing implementation output",
        evidence=[f"review_id={review_id}", f"source={source}"],
    )
    scope = ScopePolicyService(pipeline)
    git = GitService(pipeline.issue.repo_root)
    changed_files = git.changed_files()
    emit_progress(
        PipelineStage.AGENT_REVIEW,
        current_action="Collected changed files for scope and review analysis",
        evidence=[f"changed_files={len(changed_files)}"],
    )
    pending_extra_paths = scope.find_unapproved_extra_files(changed_files)

    if pending_extra_paths:
        known_extra = {}
        if pipeline.build_output:
            known_extra = {
                item.path: item
                for item in pipeline.build_output.extra_changed_files
                if item.path
            }

        extra_changed_files = [
            known_extra.get(path) or scope.infer_extra_file_reason(path)
            for path in pending_extra_paths
        ]
        cycle = ReviewCycle(
            review_id=review_id,
            source=source,
            source_rework_cycle_id=pipeline.active_rework_cycle_id,
            agent_review=AgentReview(
                review_id=review_id,
                model_name=cfg.reviewer_model,
                decision="needs_fixes",
                risk="medium",
                summary=(
                    "Review paused because files outside the approved scope were changed. "
                    "Human approval is required before substantive review can continue."
                ),
                findings=[
                    "Unapproved extra changed files were detected outside the planned paths."
                ],
                test_gaps=[],
                verification_considered=bool(
                    pipeline.build_output and pipeline.build_output.verification
                ),
            ),
            extra_changed_files=extra_changed_files,
            status="scope_gate_pending",
        )

        pipeline.review_cycles.append(cycle)
        pipeline.active_review_cycle_id = review_id
        pipeline.workflow_status = "waiting_for_human"

        render_task_file(pipeline)
        emit_waiting_for_human(
            PipelineStage.AGENT_REVIEW,
            gate="extra_files_approval",
            evidence=[f"review_id={review_id}", f"pending_extra_files={len(extra_changed_files)}"],
            conclusion="Substantive review is paused until extra-file approval is recorded.",
        )
        return dump_pipeline_state(pipeline)

    reviewer = LLMService(PipelineStage.AGENT_REVIEW)
    emit_progress(
        PipelineStage.AGENT_REVIEW,
        current_action="Requesting primary review decision",
        evidence=[f"model={cfg.reviewer_model}", f"review_id={review_id}"],
        reasoning="The reviewer checks correctness, scope, and test coverage before the workflow can proceed.",
    )
    agent_review = reviewer.complete_structured(build_review_prompt(pipeline), AgentReview)
    agent_review.review_id = review_id
    agent_review.model_name = cfg.reviewer_model

    if pipeline.build_output and pipeline.build_output.verification and pipeline.build_output.verification.any_failures:
        agent_review.decision = "needs_fixes"
        if agent_review.risk == "low":
            agent_review.risk = "medium"
        agent_review.summary = (
            agent_review.summary + " Verification failures present, so review cannot approve."
        ).strip()

    cycle = ReviewCycle(
        review_id=review_id,
        source=source,
        source_rework_cycle_id=pipeline.active_rework_cycle_id,
        agent_review=agent_review,
        status="in_review" if agent_review.decision == "escalate" else (
            "approved" if agent_review.decision == "approved" else "needs_fixes"
        ),
    )

    pipeline.review_cycles.append(cycle)
    pipeline.active_review_cycle_id = review_id

    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.AGENT_REVIEW,
        status=cycle.status,
        evidence=[
            f"review_id={review_id}",
            f"decision={agent_review.decision}",
            f"risk={agent_review.risk}",
            f"findings={len(agent_review.findings)}",
            f"test_gaps={len(agent_review.test_gaps)}",
        ],
        conclusion=agent_review.summary,
    )
    return dump_pipeline_state(pipeline)

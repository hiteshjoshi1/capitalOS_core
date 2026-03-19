from __future__ import annotations

from orchestration.models.review import AgentReview, ReviewCycle
from orchestration.prompts.review import build_review_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.llm import LLMService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "agent_review"
    pipeline.workflow_status = "running"

    cfg = get_config()
    review_id = pipeline.next_review_id()
    source = "rework" if pipeline.active_rework_cycle_id else "build"

    reviewer = LLMService(model=cfg.reviewer_model)
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
    return dump_pipeline_state(pipeline)
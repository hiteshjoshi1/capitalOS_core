from __future__ import annotations

from orchestration.models.review import AgentReview
from orchestration.prompts.review import build_escalation_review_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.llm import LLMService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "agent_review"
    pipeline.workflow_status = "running"

    cfg = get_config()
    cycle = pipeline.get_active_review_cycle()
    if not cycle or not cycle.agent_review:
        raise RuntimeError("Escalation review requires an active primary review cycle.")

    escalation = LLMService(model=cfg.review_escalation_model).complete_structured(
        build_escalation_review_prompt(pipeline, cycle.agent_review),
        AgentReview,
    )
    escalation.review_id = cycle.review_id
    escalation.model_name = cfg.review_escalation_model
    cycle.escalation_review = escalation

    effective = cycle.effective_agent_decision()
    cycle.status = "approved" if effective == "approved" else "needs_fixes"

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
from __future__ import annotations

from langgraph.types import interrupt

from orchestration.models.review import HumanReview
from orchestration.render import render_task_file
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "human_review"
    pipeline.workflow_status = "waiting_for_human"

    cycle = pipeline.get_active_review_cycle()
    if not cycle:
        raise RuntimeError("No active review cycle available for human review.")

    effective_review = cycle.escalation_review or cycle.agent_review
    if not effective_review:
        raise RuntimeError("Human review requires an agent or escalation review.")

    payload = {
        "gate": "human_review",
        "review_id": cycle.review_id,
        "agent_review": effective_review.model_dump(mode="json"),
        "expected_resume_schema": {
            "decision": "approved|needs_fixes",
            "reviewer": "non-empty string",
            "notes": "string; required if needs_fixes",
            "questions": ["string"],
            "response_requirements": ["string"],
            "unresolved_comments": ["string"],
        },
    }

    decision_raw = interrupt(payload)
    if "gate_type" in decision_raw:
        decision_raw.pop("gate_type", None)

    human_decision = HumanReview.model_validate(
        {
            "review_id": cycle.review_id,
            **decision_raw,
        }
    )

    cycle.human_review = human_decision
    agent_decision = cycle.effective_agent_decision()

    if agent_decision == "approved" and human_decision.decision == "approved":
        cycle.status = "approved"
        pipeline.workflow_status = "approved"
    else:
        cycle.status = "needs_fixes"
        pipeline.workflow_status = "needs_fixes"

    render_task_file(pipeline)
    return dump_pipeline_state(pipeline)
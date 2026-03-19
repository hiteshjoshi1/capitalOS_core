from __future__ import annotations

from orchestration.state import GraphState, load_pipeline_state


def route_from_dispatch(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return pipeline.requested_entrypoint or "prepare"


def route_after_prepare(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "plan"


def route_after_plan(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "human_approval_gate"


def route_after_human_approval(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    decision = pipeline.human_gate_decisions.get("plan_approval")
    if not decision:
        return "human_approval_gate"
    if pipeline.execution_mode == "step":
        return "__end__"
    return "build" if decision.decision == "approved" else "__end__"


def route_after_build(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "agent_review"


def route_after_agent_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if not cycle or not cycle.agent_review:
        return "__end__"

    if pipeline.execution_mode == "step":
        return "__end__"

    if cycle.agent_review.decision == "escalate" or cycle.agent_review.risk == "high":
        return "escalation_review"

    return "human_review"


def route_after_escalation_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "human_review"


def route_after_human_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if not cycle:
        return "__end__"
    if pipeline.execution_mode == "step":
        return "__end__"
    if cycle.status == "approved":
        return "ship"
    return "rework_analysis"


def route_after_rework_analysis(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "rework_implementation"


def route_after_rework_implementation(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return "__end__" if pipeline.execution_mode == "step" else "agent_review"
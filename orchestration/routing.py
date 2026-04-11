from __future__ import annotations

from orchestration.services.config import get_config
from orchestration.state import GraphState, load_pipeline_state


def route_from_dispatch(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    return pipeline.requested_entrypoint or "prepare"


def route_after_prepare(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.pipeline_version == "v3":
        return "agent_run"
    return "plan"


def route_after_plan(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.pipeline_version == "v3":
        return "agent_run"
    return "human_approval_gate"


def route_after_human_approval(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.build_output and pipeline.build_output.retry_request is not None:
        decision = pipeline.human_gate_decisions.get("build_retry_approval")
        if not decision:
            return "human_approval_gate"
        return "build" if decision.decision == "approved" else "__end__"

    decision = pipeline.human_gate_decisions.get("plan_approval")
    if not decision:
        return "human_approval_gate"
    return "build" if decision.decision == "approved" else "__end__"


def route_after_build(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.workflow_status == "blocked":
        if pipeline.build_output and pipeline.build_output.retry_request is not None:
            return "human_approval_gate"
        return "__end__"
    return "agent_review"


def route_after_agent_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if not cycle or not cycle.agent_review:
        return "__end__"

    if cycle.agent_review.decision == "escalate" or cycle.agent_review.risk == "high":
        return "escalation_review"

    if cycle.agent_review.decision == "approved":
        return "human_review"

    if len(pipeline.rework_cycles) >= get_config().max_rework_cycles:
        return "human_review"

    return "rework_analysis"


def route_after_escalation_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if not cycle or not cycle.escalation_review:
        return "__end__"
    if cycle.escalation_review.decision == "approved":
        return "human_review"
    if len(pipeline.rework_cycles) >= get_config().max_rework_cycles:
        return "human_review"
    return "rework_analysis"


def route_after_human_review(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if not cycle:
        return "__end__"
    if cycle.status == "scope_approved":
        return "agent_review"
    if cycle.status == "approved":
        return "ship"
    return "rework_analysis"


def route_after_rework_analysis(state: GraphState) -> str:
    load_pipeline_state(state)
    return "rework_implementation"


def route_after_rework_implementation(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    cycle = pipeline.get_active_review_cycle()
    if (
        cycle
        and cycle.status == "scope_gate_pending"
        and cycle.source == "rework"
        and cycle.source_rework_cycle_id == pipeline.active_rework_cycle_id
    ):
        return "human_review"
    rework = pipeline.get_active_rework_cycle()
    if rework and rework.status == "blocked":
        return "__end__"
    return "agent_review"


def route_after_agent_run(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.workflow_status == "blocked":
        return "__end__"
    return "deterministic_gates"


def route_after_deterministic_gates(state: GraphState) -> str:
    pipeline = load_pipeline_state(state)
    if pipeline.workflow_status in {"blocked", "failed", "waiting_for_human"}:
        return "__end__"
    return "ship"

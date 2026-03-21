from __future__ import annotations

from langgraph.types import interrupt

from orchestration.models.review import HumanDecision, HumanReview
from orchestration.render import render_task_file
from orchestration.services.console import emit_stage_end, emit_stage_start, emit_waiting_for_human
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "human_review"
    pipeline.workflow_status = "waiting_for_human"

    cycle = pipeline.get_active_review_cycle()
    if not cycle:
        raise RuntimeError("No active review cycle available for human review.")
    emit_stage_start(
        "human_review",
        current_action="Preparing human review payload",
        evidence=[f"review_id={cycle.review_id}", f"status={cycle.status}"],
    )

    if cycle.extra_changed_files and cycle.extra_files_review is None:
        payload = {
            "gate": "extra_files_approval",
            "review_id": cycle.review_id,
            "extra_changed_files": [
                item.model_dump(mode="json") for item in cycle.extra_changed_files
            ],
            "expected_resume_schema": {
                "gate_type": "extra_files_approval",
                "decision": "approved|needs_fixes",
                "reviewer": "non-empty string",
                "notes": "string; required if needs_fixes",
                "questions": ["string"],
                "response_requirements": ["string"],
                "unresolved_comments": ["string"],
            },
        }

        render_task_file(pipeline)
        emit_waiting_for_human(
            "human_review",
            gate="extra_files_approval",
            evidence=[f"review_id={cycle.review_id}", f"extra_files={len(cycle.extra_changed_files)}"],
            conclusion="Human approval is required for files outside the planned scope.",
        )
        decision_raw = interrupt(payload)
        decision_raw.setdefault("gate_type", "extra_files_approval")

        decision = HumanDecision.model_validate(decision_raw)
        cycle.extra_files_review = decision
        pipeline.human_gate_decisions[f"extra_files_approval:{cycle.review_id}"] = decision

        if decision.decision == "approved":
            pipeline.approve_extra_files(cycle.extra_changed_files)
            cycle.status = "scope_approved"
            pipeline.workflow_status = "running"
        else:
            cycle.status = "needs_fixes"
            pipeline.workflow_status = "needs_fixes"

        render_task_file(pipeline)
        emit_stage_end(
            "human_review",
            status=cycle.status,
            evidence=[f"gate=extra_files_approval", f"decision={decision.decision}", f"reviewer={decision.reviewer}"],
            conclusion="Extra-file approval decision recorded.",
        )
        return dump_pipeline_state(pipeline)

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

    render_task_file(pipeline)
    emit_waiting_for_human(
        "human_review",
        gate="human_review",
        evidence=[f"review_id={cycle.review_id}", f"agent_decision={effective_review.decision}"],
        conclusion="Final human review is required before ship or further rework.",
    )
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
    emit_stage_end(
        "human_review",
        status=cycle.status,
        evidence=[f"decision={human_decision.decision}", f"reviewer={human_decision.reviewer}"],
        conclusion="Human review decision recorded.",
    )
    return dump_pipeline_state(pipeline)

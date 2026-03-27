from __future__ import annotations

from langgraph.types import interrupt

from orchestration.models.review import HumanDecision
from orchestration.render import render_task_file
from orchestration.services.console import emit_stage_end, emit_stage_start, emit_waiting_for_human
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = "human_approval_gate"
    pipeline.workflow_status = "waiting_for_human"
    retry_request = pipeline.build_output.retry_request if pipeline.build_output else None
    if retry_request is not None:
        emit_stage_start(
            "human_approval_gate",
            current_action="Preparing build retry approval payload",
            evidence=[f"task_file={pipeline.issue.task_file}"],
        )
        payload = {
            "gate": "build_retry_approval",
            "issue_id": pipeline.issue.issue_id,
            "task_file": pipeline.issue.task_file,
            "retry_request": retry_request.model_dump(mode="json"),
            "expected_resume_schema": {
                "gate_type": "build_retry_approval",
                "decision": "approved|needs_fixes",
                "reviewer": "non-empty string",
                "notes": "string; required if needs_fixes",
                "questions": ["string"],
                "required_checks": ["string"],
                "response_requirements": ["string"],
                "unresolved_comments": ["string"],
                "approved_retry_count": "integer > 0 when decision is approved",
            },
        }
        waiting_conclusion = (
            "Build retries are exhausted. Human approval is required to grant more retries or provide guidance."
        )
        gate_name = "build_retry_approval"
    else:
        emit_stage_start(
            "human_approval_gate",
            current_action="Preparing plan approval payload",
            evidence=[f"task_file={pipeline.issue.task_file}"],
        )
        payload = {
            "gate": "plan_approval",
            "issue_id": pipeline.issue.issue_id,
            "task_file": pipeline.issue.task_file,
            "plan_summary": pipeline.plan_output.summary if pipeline.plan_output else "",
            "acceptance_criteria": pipeline.plan_output.acceptance_criteria if pipeline.plan_output else [],
            "expected_resume_schema": {
                "gate_type": "plan_approval",
                "decision": "approved|needs_fixes",
                "reviewer": "non-empty string",
                "notes": "string; required if needs_fixes",
                "questions": ["string"],
                "required_checks": ["string"],
                "response_requirements": ["string"],
                "unresolved_comments": ["string"],
            },
        }
        waiting_conclusion = "Plan approval is required before build can begin."
        gate_name = "plan_approval"

    render_task_file(pipeline)
    emit_waiting_for_human(
        "human_approval_gate",
        gate=gate_name,
        evidence=[
            f"acceptance_criteria={len(payload.get('acceptance_criteria', []))}",
            f"requested_retry_count={retry_request.requested_retry_count if retry_request else 0}",
        ],
        conclusion=waiting_conclusion,
    )
    decision_raw = interrupt(payload)
    decision = HumanDecision.model_validate(decision_raw)
    if retry_request is not None:
        if decision.gate_type != "build_retry_approval":
            raise RuntimeError("Invalid gate_type for build retry approval resume payload.")
        if decision.decision == "approved":
            if not retry_request.valid_reason:
                raise RuntimeError(
                    "Build retry approval is not allowed because the builder did not provide a valid reason for more retries."
                )
            if decision.approved_retry_count <= 0:
                raise RuntimeError(
                    "Build retry approval requires a positive approved_retry_count."
                )
        pipeline.human_gate_decisions["build_retry_approval"] = decision
        pipeline.workflow_status = "running" if decision.decision == "approved" else "blocked"
    else:
        if decision.gate_type != "plan_approval":
            raise RuntimeError("Invalid gate_type for plan approval resume payload.")
        pipeline.human_gate_decisions["plan_approval"] = decision
        pipeline.workflow_status = "running" if decision.decision == "approved" else "blocked"

    render_task_file(pipeline)
    emit_stage_end(
        "human_approval_gate",
        status=pipeline.workflow_status,
        evidence=[f"decision={decision.decision}", f"reviewer={decision.reviewer}"],
        conclusion="Human plan approval decision recorded.",
    )
    return dump_pipeline_state(pipeline)

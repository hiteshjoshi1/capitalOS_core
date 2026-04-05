from __future__ import annotations

from langgraph.types import interrupt

from orchestration.models.build import BuildOutput
from orchestration.models.stage import PipelineStage
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import (
    emit_progress,
    emit_stage_end,
    emit_stage_start,
    emit_waiting_for_human,
)
from orchestration.services.git import GitService
from orchestration.services.scope import ScopePolicyService
from orchestration.services.v3_policy import V3PolicyService
from orchestration.services.verification import VerificationService
from orchestration.state import GraphState, dump_pipeline_state, load_pipeline_state


def _human_review_gate(pipeline, *, findings: list[str]) -> dict:
    payload = {
        "gate": "v3_high_risk_review",
        "findings": findings,
        "expected_resume_schema": {
            "gate_type": "v3_high_risk_review",
            "decision": "approved|needs_fixes",
            "reviewer": "non-empty string",
            "notes": "string; required if needs_fixes",
        },
    }
    render_task_file(pipeline)
    emit_waiting_for_human(
        PipelineStage.DETERMINISTIC_GATES,
        gate="v3_high_risk_review",
        evidence=[f"finding_count={len(findings)}"],
        conclusion="High-risk findings require human approval before ship.",
    )
    raw = interrupt(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("Invalid resume payload for v3_high_risk_review.")
    return raw

def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.DETERMINISTIC_GATES.value
    pipeline.workflow_status = "running"
    emit_stage_start(
        PipelineStage.DETERMINISTIC_GATES,
        current_action="Running deterministic verification and policy checks",
        evidence=[f"task={pipeline.issue.task_file}"],
    )

    cfg = get_config()
    if pipeline.agent_run_output is None:
        raise RuntimeError("deterministic_gates requires agent_run_output.")

    verification_service = VerificationService(
        pipeline.issue.repo_root,
        stage=PipelineStage.DETERMINISTIC_GATES.value,
    )
    git = GitService(pipeline.issue.repo_root)
    changed_files = git.changed_files()
    verification, retries = verification_service.run_suite_for_changed_files(
        changed_files=changed_files,
        max_attempts=cfg.max_retries,
        on_code_retry_fix=None,
    )

    for retry in retries:
        pipeline.add_retry(retry)

    build_output = BuildOutput(
        summary=pipeline.agent_run_output.summary,
        changed_files=changed_files,
        extra_changed_files=pipeline.agent_run_output.extra_changed_files,
        completed_checklist_item_ids=[item.id for item in pipeline.agent_run_output.checklist if item.required],
        implementation_notes=pipeline.agent_run_output.implementation_notes,
        verification=verification,
        builder_model=pipeline.v3_model,
    )
    pipeline.build_output = build_output

    scope_policy = ScopePolicyService(pipeline)
    allowed_paths = scope_policy.review_allowed_paths()
    policy_result = V3PolicyService(pipeline.issue.repo_root).evaluate(
        changed_files=changed_files,
        allowed_paths=allowed_paths,
        extra_changed_files=pipeline.agent_run_output.extra_changed_files,
    )
    build_output.extra_changed_files = policy_result.extra_files_with_reasons

    failures: list[str] = []
    if not pipeline.agent_run_output.semantic_intent_achieved:
        failures.append("Agent run reported semantic intent not achieved.")
    if verification.any_failures:
        failures.append(
            "Deterministic gates failed: "
            + ", ".join(result.name for result in verification.results if result.status == "fail")
        )
    if policy_result.blocked:
        failures.extend(policy_result.blockers)

    if failures:
        pipeline.errors.extend(failures)
        pipeline.workflow_status = "blocked"
        pipeline.blockers = failures
        pipeline.v3_permanent_failure_reason = failures[0]
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.DETERMINISTIC_GATES,
            status="blocked",
            evidence=[f"failures={len(failures)}", f"retry_entries={len(retries)}"],
            conclusion="Deterministic gates failed and workflow is blocked.",
        )
        return dump_pipeline_state(pipeline)

    high_risk_findings = list(pipeline.agent_run_output.risk_flags)
    if high_risk_findings and cfg.v3_require_pre_ship_human_on_high_risk:
        decision = _human_review_gate(pipeline, findings=high_risk_findings)
        reviewer = str(decision.get("reviewer", "")).strip()
        status = str(decision.get("decision", "")).strip()
        notes = str(decision.get("notes", "")).strip()
        if not reviewer:
            raise RuntimeError("v3_high_risk_review requires reviewer.")
        if status not in {"approved", "needs_fixes"}:
            raise RuntimeError("v3_high_risk_review decision must be approved or needs_fixes.")
        if status == "needs_fixes" and not notes:
            raise RuntimeError("v3_high_risk_review notes are required for needs_fixes.")
        if status == "needs_fixes":
            pipeline.workflow_status = "blocked"
            pipeline.blockers = [
                f"High-risk findings rejected by `{reviewer}`: {notes or 'No notes provided.'}"
            ]
            pipeline.v3_permanent_failure_reason = pipeline.blockers[0]
            render_task_file(pipeline)
            emit_stage_end(
                PipelineStage.DETERMINISTIC_GATES,
                status="blocked",
                evidence=[f"reviewer={reviewer}"],
                conclusion="Human rejected high-risk findings; workflow blocked.",
            )
            return dump_pipeline_state(pipeline)
        emit_progress(
            PipelineStage.DETERMINISTIC_GATES,
            current_action="High-risk findings approved by human reviewer",
            evidence=[f"reviewer={reviewer}"],
        )

    pipeline.workflow_status = "running"
    pipeline.blockers = []
    pipeline.v3_permanent_failure_reason = None
    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.DETERMINISTIC_GATES,
        status="completed",
        evidence=[f"changed_files={len(changed_files)}", f"retry_entries={len(retries)}"],
        conclusion="Deterministic gates passed.",
    )
    return dump_pipeline_state(pipeline)

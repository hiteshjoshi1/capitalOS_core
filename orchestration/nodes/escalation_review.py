from __future__ import annotations

import hashlib
import json

from orchestration.models.review import AgentReview
from orchestration.models.stage import PipelineStage
from orchestration.prompts.review import build_escalation_review_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.llm import LLMService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _escalation_input_fingerprint(review_id: str, agent_review: AgentReview, verification_failures: list[str]) -> str:
    payload = {
        "review_id": review_id,
        "agent_review": agent_review.model_dump(mode="json"),
        "verification_failures": sorted(verification_failures),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.ESCALATION_REVIEW
    pipeline.workflow_status = "running"

    cfg = get_config()
    cycle = pipeline.get_active_review_cycle()
    if not cycle or not cycle.agent_review:
        raise RuntimeError("Escalation review requires an active primary review cycle.")
    source_verification = pipeline.get_review_source_verification()
    verification_failures = [
        f"{result.name}: exit {result.exit_code}"
        for result in (source_verification.results if source_verification else [])
        if result.status == "fail"
    ]
    input_fingerprint = _escalation_input_fingerprint(
        cycle.review_id,
        cycle.agent_review,
        verification_failures,
    )

    if cycle.escalation_review and cycle.escalation_input_fingerprint == input_fingerprint:
        emit_progress(
            PipelineStage.ESCALATION_REVIEW,
            current_action="Reusing existing escalation review for identical inputs",
            evidence=[f"review_id={cycle.review_id}"],
            reasoning="The stage re-entered with the same review inputs, so the persisted escalation decision is reused.",
        )
        return dump_pipeline_state(pipeline)

    emit_stage_start(
        PipelineStage.ESCALATION_REVIEW,
        current_action="Running escalation review",
        evidence=[f"review_id={cycle.review_id}", f"primary_decision={cycle.agent_review.decision}"],
    )

    if verification_failures:
        cycle.escalation_review = AgentReview(
            review_id=cycle.review_id,
            model_name="deterministic-gate",
            decision="needs_fixes",
            risk="medium",
            summary=(
                "Deterministic verification failures are present, so escalation review is skipped "
                "until verification is green."
            ),
            findings=[
                "Verification failed before escalation: "
                + ", ".join(verification_failures)
            ],
            test_gaps=[],
            verification_considered=True,
        )
        cycle.escalation_input_fingerprint = input_fingerprint
        cycle.status = "needs_fixes"
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.ESCALATION_REVIEW,
            status=cycle.status,
            evidence=["mode=deterministic", f"verification_failures={len(verification_failures)}"],
            conclusion=cycle.escalation_review.summary,
        )
        return dump_pipeline_state(pipeline)

    unresolved_required_checks = pipeline.get_unresolved_required_checks()
    if unresolved_required_checks:
        cycle.escalation_review = AgentReview(
            review_id=cycle.review_id,
            model_name="deterministic-gate",
            decision="needs_fixes",
            risk="medium",
            summary=(
                "Required checks from the prior human review are still unresolved, so escalation review is skipped "
                "until those checks are cleared."
            ),
            findings=[
                "Unresolved required checks: " + ", ".join(unresolved_required_checks)
            ],
            test_gaps=[],
            verification_considered=True,
        )
        cycle.escalation_input_fingerprint = input_fingerprint
        cycle.status = "needs_fixes"
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.ESCALATION_REVIEW,
            status=cycle.status,
            evidence=["mode=deterministic", f"required_checks={len(unresolved_required_checks)}"],
            conclusion=cycle.escalation_review.summary,
        )
        return dump_pipeline_state(pipeline)

    emit_progress(
        PipelineStage.ESCALATION_REVIEW,
        current_action="Requesting escalation reviewer decision",
        evidence=[f"model={cfg.review_escalation_model}"],
    )
    escalation = LLMService(PipelineStage.ESCALATION_REVIEW).complete_structured(
        build_escalation_review_prompt(pipeline, cycle.agent_review),
        AgentReview,
    )
    escalation.review_id = cycle.review_id
    escalation.model_name = cfg.review_escalation_model
    cycle.escalation_review = escalation
    cycle.escalation_input_fingerprint = input_fingerprint

    effective = cycle.effective_agent_decision()
    cycle.status = "approved" if effective == "approved" else "needs_fixes"

    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.ESCALATION_REVIEW,
        status=cycle.status,
        evidence=[f"decision={escalation.decision}", f"risk={escalation.risk}", f"findings={len(escalation.findings)}"],
        conclusion=escalation.summary,
    )
    return dump_pipeline_state(pipeline)

from orchestration.models.pipeline import PipelineState
from orchestration.models.review import AgentReview


def build_review_prompt(state: PipelineState) -> str:
    verification_summary = ""
    if state.build_output and state.build_output.verification:
        verification_summary = state.build_output.verification.summary
    approved_extra_files = ""
    if state.approved_extra_files:
        approved_extra_files = "\n".join(
            f"- {item.path}: {item.reason or 'approved without recorded rationale'}"
            for item in state.approved_extra_files
        )

    return f"""
You are the primary agent reviewer.

Return strict JSON only.

Required JSON shape:
{{
  "review_id": "R1",
  "model_name": "string",
  "decision": "approved|needs_fixes|escalate",
  "risk": "low|medium|high",
  "summary": "string",
  "findings": ["string"],
  "test_gaps": ["string"],
  "verification_considered": true
}}

Escalate if uncertain, conflicting, or high risk.

Plan summary:
{state.plan_output.summary if state.plan_output else ""}

Build summary:
{state.build_output.summary if state.build_output else ""}

Verification:
{verification_summary}

Approved extra files:
{approved_extra_files or "None"}
""".strip()


def build_escalation_review_prompt(state: PipelineState, primary_review: AgentReview) -> str:
    verification_summary = ""
    if state.build_output and state.build_output.verification:
        verification_summary = state.build_output.verification.summary

    return f"""
You are the escalation reviewer.

Return strict JSON only.

Required JSON shape:
{{
  "review_id": "{primary_review.review_id}",
  "model_name": "string",
  "decision": "approved|needs_fixes|escalate",
  "risk": "low|medium|high",
  "summary": "string",
  "findings": ["string"],
  "test_gaps": ["string"],
  "verification_considered": true
}}

Primary review:
- decision: {primary_review.decision}
- risk: {primary_review.risk}
- summary: {primary_review.summary}
- findings: {primary_review.findings}
- test_gaps: {primary_review.test_gaps}

Verification:
{verification_summary}

Do not return escalate unless absolutely unavoidable.
""".strip()

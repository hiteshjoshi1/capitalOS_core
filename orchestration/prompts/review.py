from orchestration.models.pipeline import PipelineState
from orchestration.models.review import AgentReview


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def build_review_prompt(state: PipelineState) -> str:
    verification_summary = ""
    if state.build_output and state.build_output.verification:
        verification_summary = state.build_output.verification.summary
    changed_files = state.build_output.changed_files if state.build_output else []
    active_rework = state.get_active_rework_cycle()
    source_review = state.get_review_cycle(active_rework.source_review_id) if active_rework else None
    source_human_review = source_review.human_review if source_review else None
    approved_extra_files = ""
    if state.approved_extra_files:
        approved_extra_files = "\n".join(
            f"- {item.path}: {item.reason or 'approved without recorded rationale'}"
            for item in state.approved_extra_files
        )
    semantic_requirements = state.get_semantic_requirements()

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
  "semantic_verification": ["string"],
  "verification_considered": true
}}

Escalate if uncertain, conflicting, or high risk.

Plan summary:
{state.plan_output.summary if state.plan_output else ""}

Build summary:
{state.build_output.summary if state.build_output else ""}

Verification:
{verification_summary}

Changed files observed by the pipeline:
{chr(10).join(f"- {path}" for path in changed_files) or "None"}

Approved extra files:
{approved_extra_files or "None"}

Semantic requirements to verify against implementation:
{_bullets(semantic_requirements)}

Source review human guidance:
- source_review_id: {source_review.review_id if source_review else "None"}
- decision: {source_human_review.decision if source_human_review else "none"}
- notes: {source_human_review.notes if source_human_review and source_human_review.notes else "None"}
- response_requirements:
{chr(10).join(f"- {item}" for item in (source_human_review.response_requirements if source_human_review else [])) or "- None"}
- unresolved_comments:
{chr(10).join(f"- {item}" for item in (source_human_review.unresolved_comments if source_human_review else [])) or "- None"}

Review rules:
1) Base findings only on the evidence above and the repository state you directly inspect.
2) Do not claim anything about git history, branch diffs, staged-vs-committed state, or PR readiness unless that evidence is explicitly provided or you directly verify it with a tool.
3) If you decide `needs_fixes`, make the findings concrete and actionable for the next rework cycle.
4) If this review follows a rework cycle, explicitly verify whether the source review's human response requirements and unresolved comments were addressed.
5) Perform a grounded semantic verification pass against the implementation, not just string presence or stage summaries.
6) For each semantic requirement above, either record concrete evidence in `semantic_verification` or raise a concrete finding/test gap that explains what is still missing.
7) If the task changes documentation or workflow behavior, compare the docs against the real implementation sources (for example Makefile, CLI, routing, or task commands) rather than treating command mentions as sufficient.
""".strip()


def build_escalation_review_prompt(state: PipelineState, primary_review: AgentReview) -> str:
    verification_summary = ""
    if state.build_output and state.build_output.verification:
        verification_summary = state.build_output.verification.summary
    changed_files = state.build_output.changed_files if state.build_output else []
    semantic_requirements = state.get_semantic_requirements()

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
  "semantic_verification": ["string"],
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

Changed files observed by the pipeline:
{chr(10).join(f"- {path}" for path in changed_files) or "None"}

Semantic requirements to verify against implementation:
{_bullets(semantic_requirements)}

Review rules:
1) Base findings only on the evidence above and the repository state you directly inspect.
2) Do not claim anything about git history, branch diffs, staged-vs-committed state, or PR readiness unless that evidence is explicitly provided or you directly verify it with a tool.
3) If you decide `needs_fixes`, make the findings concrete and actionable for the next rework cycle.
4) Perform a grounded semantic verification pass against the implementation, not just string presence or stage summaries.
5) For each semantic requirement above, either record concrete evidence in `semantic_verification` or raise a concrete finding/test gap that explains what is still missing.
6) If the task changes documentation or workflow behavior, compare the docs against the real implementation sources (for example Makefile, CLI, routing, or task commands) rather than treating command mentions as sufficient.

Do not return escalate unless absolutely unavoidable.
""".strip()

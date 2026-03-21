from orchestration.models.pipeline import PipelineState


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None"


def build_rework_analysis_prompt(state: PipelineState) -> str:
    cycle = state.get_active_review_cycle()
    source_cycle = state.get_rework_context_review_cycle()
    effective_review = source_cycle.escalation_review or source_cycle.agent_review if source_cycle else None
    human_review = source_cycle.human_review if source_cycle else None
    extra_files_feedback = cycle.extra_files_review if cycle and cycle.extra_changed_files else None
    semantic_requirements = state.get_semantic_requirements()
    return f"""
You are doing rework analysis.

Return strict JSON only.

Required JSON shape:
{{
  "rework_cycle_id": "W1",
  "review_id": "{cycle.review_id if cycle else ''}",
  "root_cause": "string",
  "findings_addressed": ["string"],
  "planned_changes": ["string"],
  "validation_plan": ["string"],
  "unresolved_assumptions": ["string"],
  "answer_matrix": [
    {{
      "reviewer_finding": "string",
      "human_comment": "string",
      "root_cause": "string",
      "change_made": "",
      "verification_performed": "",
      "status": "planned"
    }}
  ]
}}

Latest active review state:
- active_review_id: {cycle.review_id if cycle else ""}
- active_review_source: {cycle.source if cycle else ""}
- active_review_status: {cycle.status if cycle else ""}

Source review context for this rework:
- review_id: {source_cycle.review_id if source_cycle else ""}
- review_source: {source_cycle.source if source_cycle else ""}
- review_status: {source_cycle.status if source_cycle else ""}
- review_decision: {effective_review.decision if effective_review else ""}
- risk: {effective_review.risk if effective_review else ""}
- summary: {effective_review.summary if effective_review else ""}

Reviewer findings:
{_bullets(effective_review.findings if effective_review else [])}

Reviewer test gaps:
{_bullets(effective_review.test_gaps if effective_review else [])}

Source review semantic verification:
{_bullets(effective_review.semantic_verification if effective_review else [])}

Semantic requirements that must be satisfied end-to-end:
{_bullets(semantic_requirements)}

Human review comments:
- decision: {human_review.decision if human_review else "none"}
- notes: {human_review.notes if human_review and human_review.notes else "None"}

Human questions:
{_bullets(human_review.questions if human_review else [])}

Human unresolved comments:
{_bullets(human_review.unresolved_comments if human_review else [])}

Human response requirements:
{_bullets(human_review.response_requirements if human_review else [])}

Latest extra-files gate feedback:
- decision: {extra_files_feedback.decision if extra_files_feedback else "none"}
- notes: {extra_files_feedback.notes if extra_files_feedback and extra_files_feedback.notes else "None"}

Extra-files gate questions:
{_bullets(extra_files_feedback.questions if extra_files_feedback else [])}

Extra-files gate response requirements:
{_bullets(extra_files_feedback.response_requirements if extra_files_feedback else [])}

Extra-files gate unresolved comments:
{_bullets(extra_files_feedback.unresolved_comments if extra_files_feedback else [])}

Previous rework cycles:
{_bullets([
    f"{rework.rework_cycle_id}: status={rework.status}; root_cause={rework.analysis.root_cause if rework.analysis else 'n/a'}"
    for rework in state.rework_cycles
])}

Requirements:
1) Base your analysis on the review findings and human comments above.
2) Every `findings_addressed` entry must map back to a concrete reviewer finding, test gap, or human response requirement.
3) If a reviewer claim cannot be justified by the provided evidence, call that out explicitly in `unresolved_assumptions` instead of accepting it as fact.
4) If the active review is a procedural scope gate, preserve the main task intent from the source review instead of reducing the rework to scope cleanup alone.
5) Treat the semantic requirements above as mandatory; plan concrete implementation and validation steps that prove them against the code, docs, tests, or commands involved.
""".strip()


def build_rework_implementation_prompt(state: PipelineState) -> str:
    rework = state.get_active_rework_cycle()
    analysis = rework.analysis if rework else None
    cycle = state.get_active_review_cycle()
    source_cycle = state.get_review_cycle(rework.source_review_id if rework else None)
    human_review = source_cycle.human_review if source_cycle else None
    extra_files_feedback = cycle.extra_files_review if cycle and cycle.extra_changed_files else None
    semantic_requirements = state.get_semantic_requirements()
    return f"""
You are implementing a rework.

Apply the rework changes in the repository before you respond.

Return strict JSON only.

Required JSON shape:
{{
  "rework_cycle_id": "{rework.rework_cycle_id if rework else ''}",
  "review_id": "{rework.source_review_id if rework else ''}",
  "summary": "string",
  "changed_files": ["path"],
  "verification_summary": "string",
  "completed": true
}}

Planned changes:
{_bullets(analysis.planned_changes if analysis else [])}

Validation plan:
{_bullets(analysis.validation_plan if analysis else [])}

Findings addressed:
{_bullets(analysis.findings_addressed if analysis else [])}

Source review semantic verification:
{_bullets((source_cycle.escalation_review or source_cycle.agent_review).semantic_verification if source_cycle and (source_cycle.escalation_review or source_cycle.agent_review) else [])}

Semantic requirements that must be satisfied end-to-end:
{_bullets(semantic_requirements)}

Human response requirements:
{_bullets(human_review.response_requirements if human_review else [])}

Human unresolved comments:
{_bullets(human_review.unresolved_comments if human_review else [])}

Latest extra-files gate response requirements:
{_bullets(extra_files_feedback.response_requirements if extra_files_feedback else [])}

Latest extra-files gate unresolved comments:
{_bullets(extra_files_feedback.unresolved_comments if extra_files_feedback else [])}

Hard constraints:
1) Actually modify the repo to address the rework findings before returning.
2) Keep changes scoped to the current rework cycle.
3) Do not claim filesystem write restrictions unless a real tool invocation fails and you include the concrete failed command in your summary.
4) Do not invent git-history, branch-diff, or commit-state claims unless you directly verified them with a tool during this implementation.
5) If this rework was triggered from a scope gate, still satisfy the original substantive user intent captured in the source review and human feedback.
6) Verify the implementation semantically against the requirements above before returning; do not stop at formatting fixes, string presence, or stage-summary alignment.
""".strip()

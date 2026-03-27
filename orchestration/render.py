from __future__ import annotations

from enum import Enum

from orchestration.models.build import ExtraChangedFile
from orchestration.models.pipeline import PipelineState
from orchestration.services.task_markdown import TaskMarkdownService


def _human_gate_label(gate_name: str) -> str:
    if gate_name == "plan_approval":
        return "Plan Approval"
    if gate_name == "human_review":
        return "Human Review"
    if gate_name.startswith("extra_files_approval"):
        return "Extra Files Approval"
    return gate_name.replace("_", " ").title()


def _render_extra_changed_files(items: list[ExtraChangedFile]) -> list[str]:
    if not items:
        return []
    lines = ["#### Extra Files Outside Planned Scope"]
    for item in items:
        reason = item.reason or "No reason recorded."
        lines.append(
            f"- `{item.path}`: {reason} (source: `{item.reason_source or 'unknown'}`)"
        )
    return lines


def _render_human_gate_decisions(state: PipelineState) -> list[str]:
    lines: list[str] = ["## Human Gate Decisions", ""]

    if not state.human_gate_decisions:
        lines.extend(["_No human gate decisions yet._", ""])
        return lines

    for gate_name in sorted(state.human_gate_decisions):
        decision = state.human_gate_decisions[gate_name]
        lines.append(f"### {_human_gate_label(gate_name)}")
        lines.append(f"- decision: `{decision.decision}`")
        lines.append(f"- reviewer: `{decision.reviewer}`")
        lines.append(f"- decided_at: `{decision.decided_at.isoformat()}`")
        lines.append(f"- notes: {decision.notes or '_none_'}")
        if decision.questions:
            lines.append("- questions:")
            lines.extend([f"  - {x}" for x in decision.questions])
        if decision.required_checks:
            lines.append("- required_checks:")
            lines.extend([f"  - {x}" for x in decision.required_checks])
        if decision.response_requirements:
            lines.append("- response_requirements:")
            lines.extend([f"  - {x}" for x in decision.response_requirements])
        if decision.unresolved_comments:
            lines.append("- unresolved_comments:")
            lines.extend([f"  - {x}" for x in decision.unresolved_comments])
        lines.append("")

    return lines


def _render_review_cycle(state: PipelineState) -> list[str]:
    lines: list[str] = ["## Review Cycles", ""]

    if not state.review_cycles:
        lines.extend(["_No review cycles yet._", ""])
        return lines

    for cycle in state.review_cycles:
        lines.append(f"### Review Cycle {cycle.review_id}")
        lines.append(f"- source: `{cycle.source}`")
        lines.append(f"- status: `{cycle.status}`")

        if cycle.agent_review:
            ar = cycle.agent_review
            lines.append("#### Primary Agent Review")
            lines.append(f"- model: `{ar.model_name}`")
            lines.append(f"- decision: `{ar.decision}`")
            lines.append(f"- risk: `{ar.risk}`")
            lines.append(f"- summary: {ar.summary}")
            if ar.findings:
                lines.append("- findings:")
                lines.extend([f"  - {x}" for x in ar.findings])
            if ar.test_gaps:
                lines.append("- test_gaps:")
                lines.extend([f"  - {x}" for x in ar.test_gaps])
            if ar.semantic_verification:
                lines.append("- semantic_verification:")
                lines.extend([f"  - {x}" for x in ar.semantic_verification])

        if cycle.escalation_review:
            er = cycle.escalation_review
            lines.append("#### Escalation Review")
            lines.append(f"- model: `{er.model_name}`")
            lines.append(f"- decision: `{er.decision}`")
            lines.append(f"- risk: `{er.risk}`")
            lines.append(f"- summary: {er.summary}")
            if er.findings:
                lines.append("- findings:")
                lines.extend([f"  - {x}" for x in er.findings])
            if er.test_gaps:
                lines.append("- test_gaps:")
                lines.extend([f"  - {x}" for x in er.test_gaps])
            if er.semantic_verification:
                lines.append("- semantic_verification:")
                lines.extend([f"  - {x}" for x in er.semantic_verification])

        if cycle.human_review:
            hr = cycle.human_review
            lines.append("#### Human Review")
            lines.append(f"- reviewer: `{hr.reviewer}`")
            lines.append(f"- decision: `{hr.decision}`")
            lines.append(f"- notes: {hr.notes or '_none_'}")
            if hr.questions:
                lines.append("- questions:")
                lines.extend([f"  - {x}" for x in hr.questions])
            if hr.required_checks:
                lines.append("- required_checks:")
                lines.extend([f"  - {x}" for x in hr.required_checks])
            if hr.response_requirements:
                lines.append("- response_requirements:")
                lines.extend([f"  - {x}" for x in hr.response_requirements])
            if hr.unresolved_comments:
                lines.append("- unresolved_comments:")
                lines.extend([f"  - {x}" for x in hr.unresolved_comments])

        if cycle.extra_changed_files:
            lines.extend(_render_extra_changed_files(cycle.extra_changed_files))

        if cycle.extra_files_review:
            er = cycle.extra_files_review
            lines.append("#### Extra Files Approval")
            lines.append(f"- reviewer: `{er.reviewer}`")
            lines.append(f"- decision: `{er.decision}`")
            lines.append(f"- notes: {er.notes or '_none_'}")
            if er.questions:
                lines.append("- questions:")
                lines.extend([f"  - {x}" for x in er.questions])
            if er.required_checks:
                lines.append("- required_checks:")
                lines.extend([f"  - {x}" for x in er.required_checks])
            if er.response_requirements:
                lines.append("- response_requirements:")
                lines.extend([f"  - {x}" for x in er.response_requirements])
            if er.unresolved_comments:
                lines.append("- unresolved_comments:")
                lines.extend([f"  - {x}" for x in er.unresolved_comments])

        lines.append("")

    return lines


def _render_rework_cycles(state: PipelineState) -> list[str]:
    lines: list[str] = ["## Rework Cycles", ""]

    if not state.rework_cycles:
        lines.extend(["_No rework cycles yet._", ""])
        return lines

    for cycle in state.rework_cycles:
        lines.append(f"### Rework Cycle {cycle.rework_cycle_id}")
        lines.append(f"- source_review_id: `{cycle.source_review_id}`")
        lines.append(f"- status: `{cycle.status}`")

        if cycle.analysis:
            a = cycle.analysis
            lines.append("#### Analysis")
            lines.append(f"- root_cause: {a.root_cause}")
            if a.findings_addressed:
                lines.append("- findings_addressed:")
                lines.extend([f"  - {x}" for x in a.findings_addressed])
            if a.required_checks_planned:
                lines.append("- required_checks_planned:")
                lines.extend([f"  - {x}" for x in a.required_checks_planned])
            if a.planned_changes:
                lines.append("- planned_changes:")
                lines.extend([f"  - {x}" for x in a.planned_changes])
            if a.validation_plan:
                lines.append("- validation_plan:")
                lines.extend([f"  - {x}" for x in a.validation_plan])
            if a.unresolved_assumptions:
                lines.append("- unresolved_assumptions:")
                lines.extend([f"  - {x}" for x in a.unresolved_assumptions])
            if a.answer_matrix:
                lines.append("- answer_matrix:")
                for idx, entry in enumerate(a.answer_matrix, start=1):
                    lines.append(f"  - entry_{idx}:")
                    lines.append(f"    - reviewer_finding: {entry.reviewer_finding}")
                    lines.append(f"    - human_comment: {entry.human_comment}")
                    lines.append(f"    - root_cause: {entry.root_cause}")
                    lines.append(f"    - status: {entry.status}")
                    if entry.change_made:
                        lines.append(f"    - change_made: {entry.change_made}")
                    if entry.verification_performed:
                        lines.append(f"    - verification_performed: {entry.verification_performed}")

        if cycle.implementation:
            impl = cycle.implementation
            lines.append("#### Implementation")
            lines.append(f"- summary: {impl.summary}")
            if impl.changed_files:
                lines.append("- changed_files:")
                lines.extend([f"  - `{x}`" for x in impl.changed_files])
            lines.append(f"- verification_summary: {impl.verification_summary}")
            if impl.resolved_required_checks:
                lines.append("- resolved_required_checks:")
                lines.extend([f"  - {x}" for x in impl.resolved_required_checks])
            if impl.required_check_evidence:
                lines.append("- required_check_evidence:")
                lines.extend([f"  - {x}" for x in impl.required_check_evidence])

        lines.append("")

    return lines


def _latest_outcome(state: PipelineState) -> str:
    cycle = state.get_active_review_cycle()
    rework = state.get_active_rework_cycle()

    if state.ship_result:
        return state.ship_result.summary
    if state.current_stage == "human_approval_gate" and state.build_output and state.build_output.retry_request:
        return state.build_output.retry_request.summary
    if cycle and cycle.human_review:
        return f"Human review {cycle.human_review.decision}: {cycle.human_review.notes or cycle.human_review.decision}"
    if cycle and (cycle.escalation_review or cycle.agent_review):
        review = cycle.escalation_review or cycle.agent_review
        return f"Review {review.decision}: {review.summary}"
    if rework and rework.implementation:
        return rework.implementation.summary
    if rework and rework.analysis:
        return rework.analysis.root_cause
    if state.build_output:
        return state.build_output.summary
    if state.plan_output:
        return state.plan_output.summary
    if state.blockers:
        return state.blockers[-1]
    return "No workflow outcome recorded yet."


def _display_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _effective_workflow_status(state: PipelineState) -> str:
    cycle = state.get_active_review_cycle()
    if cycle and cycle.status == "scope_gate_pending":
        return "waiting_for_human"
    rework = state.get_active_rework_cycle()
    if rework and rework.status == "blocked":
        return "blocked"
    return _display_value(state.workflow_status)


def _failed_verification_checks(state: PipelineState) -> list[str]:
    verification = None
    rework = state.get_active_rework_cycle()
    if rework and rework.implementation and rework.implementation.verification:
        verification = rework.implementation.verification
    elif state.build_output and state.build_output.verification:
        verification = state.build_output.verification

    if verification is None:
        return []
    return [result.name for result in verification.results if result.status == "fail"]


def _blocked_reason(state: PipelineState, workflow_status: str) -> str | None:
    if workflow_status != "blocked":
        return None
    if state.blockers:
        return state.blockers[-1]

    failed_checks = _failed_verification_checks(state)
    if failed_checks:
        return "Verification failed: " + ", ".join(failed_checks)

    rework = state.get_active_rework_cycle()
    if rework and rework.status == "blocked":
        return f"Rework cycle {rework.rework_cycle_id} is marked blocked."

    return "The workflow is blocked, but no explicit blocker was recorded."


def _retry_gate_pending(state: PipelineState) -> bool:
    return bool(
        state.build_output
        and state.build_output.retry_request is not None
        and _display_value(state.current_stage) == "human_approval_gate"
        and _effective_workflow_status(state) == "waiting_for_human"
    )


def _latest_retry_entries(state: PipelineState, labels: list[str] | None = None) -> list:
    latest_by_label = {}
    for entry in state.retry_log:
        if labels and entry.label not in labels:
            continue
        latest_by_label[entry.label] = entry
    return [latest_by_label[label] for label in sorted(latest_by_label)]


def _retry_diagnostics(state: PipelineState) -> list[str]:
    failed_checks = _failed_verification_checks(state)
    retry_entries = _latest_retry_entries(state, failed_checks or None)
    diagnostics: list[str] = []

    for entry in retry_entries:
        note = entry.notes or "No retry note recorded."
        diagnostics.append(
            f"`{entry.label}` stopped after attempt {entry.attempt}/{entry.max_attempts}: {note}"
        )
    return diagnostics


def _stopped_due_to(state: PipelineState, workflow_status: str) -> str | None:
    if workflow_status != "blocked":
        return None

    diagnostics = _retry_diagnostics(state)
    if diagnostics:
        for item in diagnostics:
            if "Auto-fix failed after code failure:" in item:
                return "The automated retry fixer crashed before the retry budget was exhausted."
            if "Code failure after max retry budget:" in item:
                return "The verification retry budget was exhausted."
            if "same signature after an auto-fix attempt" in item:
                return "The same failure repeated after an automated fix, so retries stopped to avoid thrash."

    if _failed_verification_checks(state):
        return "Verification remained red after the available automated recovery steps."
    return None


def _halt_reason(state: PipelineState, workflow_status: str) -> str | None:
    rework = state.get_active_rework_cycle()
    current_stage = _display_value(state.current_stage)
    if workflow_status == "blocked" and current_stage == "rework_implementation" and rework:
        return (
            f"Rework cycle {rework.rework_cycle_id} is blocked. "
            "The graph intentionally ends after a blocked rework implementation."
        )
    return None


def _next_action(state: PipelineState) -> str:
    workflow_status = _effective_workflow_status(state)
    current_stage = _display_value(state.current_stage)

    if workflow_status == "waiting_for_human":
        if current_stage == "human_approval_gate" and state.build_output and state.build_output.retry_request:
            retry_request = state.build_output.retry_request
            if retry_request and retry_request.valid_reason:
                return (
                    "Human to approve an additional retry count or provide guidance before build runs again."
                )
            return "Human to provide guidance because build exhausted retries without a valid reason for more attempts."
        if current_stage == "human_approval_gate":
            return "Human to approve or reject the plan before build starts."
        if current_stage == "human_review":
            cycle = state.get_active_review_cycle()
            if cycle and cycle.status == "scope_gate_pending":
                return "Human to approve or reject out-of-scope files introduced during rework before review continues."
            return "Human to approve, request rework, and review any extra changed files."
        return "Human input is required before the workflow can continue."

    if workflow_status == "blocked":
        if current_stage == "rework_implementation":
            return "Inspect the failed verification checks, update the repo, and rerun rework on the same thread."
        if state.build_output and state.build_output.retry_request:
            retry_request = state.build_output.retry_request
            if retry_request and retry_request.valid_reason:
                return "Resume the build-retry approval gate or provide additional human guidance."
            return "Provide human guidance for the blocked build before rerunning."
        return "Inspect blockers and rerun the appropriate stage after adding new context."

    if workflow_status == "approved":
        return "Run ship to commit and push the approved changes."
    if workflow_status == "shipped":
        return "No action required."
    if current_stage == "build":
        return "Build verification will finish before review can proceed."
    if current_stage in {"agent_review", "escalation_review"}:
        return "Review will decide whether to approve, request rework, or escalate."
    if current_stage == "rework_analysis":
        return "Rework analysis should produce the next implementation plan."
    if current_stage == "rework_implementation":
        return "Rework implementation should modify the repo and return to review."
    if current_stage == "plan":
        return "Human plan approval is the next gate."
    return "Workflow execution is in progress."


def _active_requirements(state: PipelineState) -> list[str]:
    items = state.get_semantic_requirements()
    if items:
        return items
    if state.plan_output and state.plan_output.acceptance_criteria:
        return [f"Acceptance criterion: {item}" for item in state.plan_output.acceptance_criteria]
    return ["No active requirements recorded yet."]


def render_execution_journal(state: PipelineState) -> str:
    workflow_status = _effective_workflow_status(state)
    current_stage = _display_value(state.current_stage)
    active_review = state.get_active_review_cycle()
    active_rework = state.get_active_rework_cycle()
    failed_checks = _failed_verification_checks(state)
    blocked_reason = _blocked_reason(state, workflow_status)
    retry_gate_pending = _retry_gate_pending(state)
    retry_diagnostics = _retry_diagnostics(state)
    stopped_due_to = _stopped_due_to(state, workflow_status)
    halt_reason = _halt_reason(state, workflow_status)

    snapshot_lines = [
        f"- latest_outcome: {_latest_outcome(state)}",
        f"- next_action: {_next_action(state)}",
    ]
    if active_review:
        snapshot_lines.append(
            f"- active_review_cycle: `{active_review.review_id}` (`{active_review.status}`)"
        )
    if active_rework:
        snapshot_lines.append(
            f"- active_rework_cycle: `{active_rework.rework_cycle_id}` (`{active_rework.status}`)"
        )
    if failed_checks:
        snapshot_lines.append(
            f"- latest_failed_checks: {', '.join(f'`{name}`' for name in failed_checks)}"
        )
    snapshot_lines.append(f"- retry_gate_pending: `{'yes' if retry_gate_pending else 'no'}`")
    if retry_diagnostics:
        snapshot_lines.extend(f"- retry_detail: {item}" for item in retry_diagnostics)
    if blocked_reason:
        snapshot_lines.append(f"- blocked_reason: {blocked_reason}")
    if stopped_due_to:
        snapshot_lines.append(f"- stopped_due_to: {stopped_due_to}")
    if halt_reason:
        snapshot_lines.append(f"- halt_reason: {halt_reason}")

    lines: list[str] = [
        "## Execution Journal",
        f"**Current Stage**: `{current_stage}`",
        f"**Workflow Status**: `{workflow_status}`",
        "",
        "## Workflow Snapshot",
        *snapshot_lines,
        "",
        "## Active Requirements",
        *[f"- {item}" for item in _active_requirements(state)],
        "",
    ]

    if state.prepare_result:
        lines.extend(["## Prepare", state.prepare_result.summary or "_No summary._", ""])

    if state.plan_output:
        lines.extend(
            [
                "## Plan Summary",
                state.plan_output.summary,
                "",
                "### Architecture Decisions",
                *[f"- {x}" for x in state.plan_output.architecture_decisions],
                "",
                "### Acceptance Criteria",
                *[f"- {x}" for x in state.plan_output.acceptance_criteria],
                "",
            ]
        )
        if state.plan_output.planned_paths:
            lines.extend(
                [
                    "### Planned Paths",
                    *[f"- `{x}`" for x in state.plan_output.planned_paths],
                    "",
                ]
            )

    if state.build_output:
        lines.extend(["## Build Summary", state.build_output.summary, ""])
        if state.build_output.changed_files:
            lines.append("### Changed Files")
            lines.extend(f"- `{x}`" for x in state.build_output.changed_files)
            lines.append("")
        if state.build_output.extra_changed_files:
            lines.append("### Extra Files Outside Planned Scope")
            for item in state.build_output.extra_changed_files:
                lines.append(
                    f"- `{item.path}`: {item.reason or 'No reason recorded.'} "
                    f"(source: `{item.reason_source or 'unknown'}`)"
                )
            lines.append("")
        if state.build_output.verification:
            lines.extend(
                [
                    "## Latest Verification",
                    state.build_output.verification.summary,
                    "",
                ]
            )

    lines.extend(_render_human_gate_decisions(state))
    lines.extend(_render_review_cycle(state))
    lines.extend(_render_rework_cycles(state))

    if state.retry_log:
        lines.append("## Retry Log")
        for entry in state.retry_log:
            line = (
                f"- {entry.label}: attempt {entry.attempt}/{entry.max_attempts}, "
                f"class={entry.classification}, exit={entry.exit_code}, "
                f"log={entry.failure_log_path or 'n/a'}"
            )
            if entry.notes:
                line += f", notes={entry.notes}"
            lines.append(line)
        lines.append("")

    if state.blockers:
        lines.extend(["## Blockers", *[f"- {x}" for x in state.blockers], ""])

    if state.ship_result:
        lines.extend(["## Ship Result", state.ship_result.summary, ""])
        if state.ship_result.pr_url:
            lines.extend([f"- PR: {state.ship_result.pr_url}", ""])

    return "\n".join(lines).strip()


def render_task_file(state: PipelineState) -> None:
    svc = TaskMarkdownService(state.issue.repo_root)
    content = svc.read(state.issue.task_file)
    rendered = render_execution_journal(state)
    updated = svc.replace_machine_rendered_region(content, rendered)
    svc.write(state.issue.task_file, updated)

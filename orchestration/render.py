from __future__ import annotations

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

        if cycle.human_review:
            hr = cycle.human_review
            lines.append("#### Human Review")
            lines.append(f"- reviewer: `{hr.reviewer}`")
            lines.append(f"- decision: `{hr.decision}`")
            lines.append(f"- notes: {hr.notes or '_none_'}")
            if hr.questions:
                lines.append("- questions:")
                lines.extend([f"  - {x}" for x in hr.questions])
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

        lines.append("")

    return lines


def render_execution_journal(state: PipelineState) -> str:
    lines: list[str] = [
        "## Execution Journal",
        f"**Current Stage**: `{state.current_stage}`",
        f"**Workflow Status**: `{state.workflow_status}`",
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

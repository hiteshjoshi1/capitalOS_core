from __future__ import annotations

from orchestration.models.build import BuildOutput, ExtraChangedFile
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.review import AgentReview, HumanDecision, ReviewCycle
from orchestration.render import render_execution_journal


def _base_state() -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="123",
            slug="test",
            title="Test",
            task_file="tasks/issue-123-test.md",
            repo_root=".",
            branch="feature/issue-123-test",
        ),
        current_stage="human_approval_gate",
        workflow_status="running",
        execution_mode="step",
        plan_output=PlanOutput(
            summary="Planned workflow",
            architecture_decisions=["Use LangGraph"],
            risks=["Low"],
            open_questions=[],
            acceptance_criteria=["Workflow runs"],
            planned_paths=["orchestration/"],
            checklist=[],
        ),
    )


def test_render_execution_journal_includes_plan_approval_details() -> None:
    state = _base_state()
    state.human_gate_decisions["plan_approval"] = HumanDecision(
        gate_type="plan_approval",
        decision="needs_fixes",
        reviewer="Hitesh",
        notes="Narrow scope to dashboard only.",
        questions=["Can this be split?"],
        response_requirements=["Tighten acceptance criteria"],
        unresolved_comments=["Do not change unrelated pages"],
    )

    rendered = render_execution_journal(state)

    assert "## Human Gate Decisions" in rendered
    assert "### Plan Approval" in rendered
    assert "- decision: `needs_fixes`" in rendered
    assert "- reviewer: `Hitesh`" in rendered
    assert "- notes: Narrow scope to dashboard only." in rendered
    assert "Can this be split?" in rendered
    assert "Tighten acceptance criteria" in rendered
    assert "Do not change unrelated pages" in rendered


def test_render_execution_journal_includes_extra_files_context() -> None:
    state = _base_state()
    state.build_output = BuildOutput(
        summary="Implemented the task and updated workflow support files.",
        changed_files=["web/src/App.tsx", "orchestration/cli.py"],
        extra_changed_files=[
            ExtraChangedFile(
                path="orchestration/cli.py",
                reason="Workflow support change required to let the review gate resume correctly.",
                reason_source="builder",
            )
        ],
    )
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Scope approval required.",
            ),
            extra_changed_files=[
                ExtraChangedFile(
                    path="orchestration/cli.py",
                    reason="Workflow support change required to let the review gate resume correctly.",
                    reason_source="builder",
                )
            ],
            extra_files_review=HumanDecision(
                gate_type="extra_files_approval",
                decision="approved",
                reviewer="Hitesh",
                notes="Support file change is acceptable.",
            ),
            status="scope_approved",
        )
    )
    state.active_review_cycle_id = "R1"

    rendered = render_execution_journal(state)

    assert "### Extra Files Outside Planned Scope" in rendered
    assert "`orchestration/cli.py`" in rendered
    assert "Workflow support change required to let the review gate resume correctly." in rendered
    assert "#### Extra Files Approval" in rendered
    assert "Support file change is acceptable." in rendered

from __future__ import annotations

from orchestration.models.build import BuildOutput, ExtraChangedFile, RetryEntry
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.rework import ReworkCycle, ReworkImplementationResult
from orchestration.models.review import AgentReview, HumanDecision, ReviewCycle
from orchestration.models.verification import VerificationCommandResult, VerificationEvidence
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
        reviewer="TestReviewer",
        notes="Narrow scope to dashboard only.",
        questions=["Can this be split?"],
        response_requirements=["Tighten acceptance criteria"],
        unresolved_comments=["Do not change unrelated pages"],
    )

    rendered = render_execution_journal(state)

    assert "## Human Gate Decisions" in rendered
    assert "### Plan Approval" in rendered
    assert "- decision: `needs_fixes`" in rendered
    assert "- reviewer: `TestReviewer`" in rendered
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
                reviewer="TestReviewer",
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


def test_render_execution_journal_includes_semantic_verification() -> None:
    state = _base_state()
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Docs still mismatch behavior.",
                findings=["Fix the respond command description."],
                semantic_verification=[
                    "Compared ai-task-flow.md against Makefile and found task-respond documented with the wrong semantics."
                ],
            ),
            status="needs_fixes",
        )
    )

    rendered = render_execution_journal(state)

    assert "- semantic_verification:" in rendered
    assert "Compared ai-task-flow.md against Makefile and found task-respond documented with the wrong semantics." in rendered


def test_render_execution_journal_surfaces_blocked_rework_reason_and_next_step() -> None:
    state = _base_state()
    state.current_stage = "rework_implementation"
    state.workflow_status = "running"
    state.review_cycles.append(
        ReviewCycle(
            review_id="R8",
            source="build",
            agent_review=AgentReview(
                review_id="R8",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Needs rework.",
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R8"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W5",
            source_review_id="R8",
            implementation=ReworkImplementationResult(
                rework_cycle_id="W5",
                review_id="R8",
                summary="Rework applied but verification failed.",
                verification=VerificationEvidence(
                    results=[
                        VerificationCommandResult(
                            name="test-backend",
                            command="make test-backend",
                            status="fail",
                            exit_code=2,
                        ),
                        VerificationCommandResult(
                            name="e2e",
                            command="make e2e",
                            status="fail",
                            exit_code=2,
                        ),
                    ],
                    any_failures=True,
                ),
            ),
            status="blocked",
        )
    )
    state.active_rework_cycle_id = "W5"
    state.blockers.append("Verification suite failed during rework: test-backend, e2e")
    state.retry_log.extend(
        [
            RetryEntry(
                label="test-backend",
                attempt=1,
                max_attempts=3,
                command="make test-backend",
                exit_code=2,
                classification="code",
                notes="Auto-fix failed after code failure: callback mismatch",
            ),
            RetryEntry(
                label="e2e",
                attempt=1,
                max_attempts=3,
                command="make e2e",
                exit_code=2,
                classification="code",
                notes="Auto-fix failed after code failure: callback mismatch",
            ),
        ]
    )

    rendered = render_execution_journal(state)

    assert "**Current Stage**: `rework_implementation`" in rendered
    assert "**Workflow Status**: `blocked`" in rendered
    assert "- active_review_cycle: `R8` (`needs_fixes`)" in rendered
    assert "- active_rework_cycle: `W5` (`blocked`)" in rendered
    assert "- latest_failed_checks: `test-backend`, `e2e`" in rendered
    assert "- retry_gate_pending: `no`" in rendered
    assert "retry_detail: `e2e` stopped after attempt 1/3: Auto-fix failed after code failure" in rendered
    assert "retry_detail: `test-backend` stopped after attempt 1/3: Auto-fix failed after code failure" in rendered
    assert "- blocked_reason: Verification suite failed during rework: test-backend, e2e" in rendered
    assert "- stopped_due_to: The automated retry fixer crashed before the retry budget was exhausted." in rendered
    assert "The graph intentionally ends after a blocked rework implementation." in rendered
    assert "rerun rework on the same thread" in rendered


def test_render_execution_journal_shows_waiting_human_for_rework_scope_gate() -> None:
    state = _base_state()
    state.current_stage = "human_review"
    state.workflow_status = "waiting_for_human"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W7",
            source_review_id="R8",
            status="blocked",
        )
    )
    state.active_rework_cycle_id = "W7"
    state.review_cycles.append(
        ReviewCycle(
            review_id="R9",
            source="rework",
            source_rework_cycle_id="W7",
            extra_changed_files=[
                ExtraChangedFile(
                    path="orchestration/cli.py",
                    reason="Pipeline support change.",
                    reason_source="builder",
                )
            ],
            status="scope_gate_pending",
        )
    )
    state.active_review_cycle_id = "R9"

    rendered = render_execution_journal(state)

    assert "**Current Stage**: `human_review`" in rendered
    assert "**Workflow Status**: `waiting_for_human`" in rendered
    assert "- active_review_cycle: `R9` (`scope_gate_pending`)" in rendered
    assert "- active_rework_cycle: `W7` (`blocked`)" in rendered
    assert "Human to approve or reject out-of-scope files introduced during rework before review continues." in rendered
    assert "- blocked_reason:" not in rendered

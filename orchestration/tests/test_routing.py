from langgraph.checkpoint.memory import InMemorySaver

from orchestration.graph import build_graph
from orchestration.models.issue import IssueMetadata
from orchestration.models.build import ExtraChangedFile
from orchestration.models.pipeline import PipelineState
from orchestration.models.review import HumanDecision, ReviewCycle, AgentReview, HumanReview
from orchestration.models.rework import ReworkAnalysis, ReworkCycle
from orchestration.routing import (
    route_after_agent_review,
    route_after_build,
    route_after_escalation_review,
    route_after_human_approval,
    route_after_human_review,
    route_after_plan,
    route_after_prepare,
    route_after_rework_analysis,
    route_after_rework_implementation,
)
from orchestration.state import dump_pipeline_state


def _base_state(execution_mode: str = "workflow") -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="123",
            slug="test",
            title="Test",
            task_file="tasks/issue-123-test.md",
            repo_root=".",
            branch="feature/issue-123-test",
        ),
        execution_mode=execution_mode,
    )


def test_route_after_prepare_step_advances_to_agent_run():
    state = _base_state(execution_mode="step")
    state.current_stage = "prepare"
    state.workflow_status = "running"

    assert route_after_prepare(dump_pipeline_state(state)) == "agent_run"


def test_route_after_plan_step_advances_to_agent_run():
    state = _base_state(execution_mode="step")
    state.current_stage = "plan"
    state.workflow_status = "running"

    assert route_after_plan(dump_pipeline_state(state)) == "agent_run"


def test_route_after_plan_workflow_still_advances_to_agent_run():
    state = _base_state()
    state.current_stage = "plan"
    state.workflow_status = "running"

    assert route_after_plan(dump_pipeline_state(state)) == "agent_run"


def test_route_after_human_approval_step_advances_to_build_when_approved():
    state = _base_state(execution_mode="step")
    state.human_gate_decisions["plan_approval"] = HumanDecision(
        gate_type="plan_approval",
        decision="approved",
        reviewer="Hitesh",
        notes="Approved",
    )

    assert route_after_human_approval(dump_pipeline_state(state)) == "build"


def test_route_after_build_step_advances_to_agent_review():
    state = _base_state(execution_mode="step")
    state.current_stage = "build"
    state.workflow_status = "running"

    assert route_after_build(dump_pipeline_state(state)) == "agent_review"


def test_route_after_build_blocked_ends():
    state = _base_state(execution_mode="step")
    state.current_stage = "build"
    state.workflow_status = "blocked"

    assert route_after_build(dump_pipeline_state(state)) == "__end__"


def test_route_after_agent_review_step_advances_to_human_review():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="approved",
            risk="low",
            summary="ok",
        ),
        status="approved",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_agent_review(dump_pipeline_state(state)) == "human_review"


def test_route_after_agent_review_needs_fixes_goes_to_rework():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="needs work",
        ),
        status="needs_fixes",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_agent_review(dump_pipeline_state(state)) == "rework_analysis"


def test_route_after_agent_review_needs_fixes_goes_to_human_review_after_max_reworks(
    monkeypatch,
):
    state = _base_state(execution_mode="workflow")
    state.rework_cycles.extend(
        [
            ReworkCycle(rework_cycle_id="W1", source_review_id="R1", status="implementation_complete"),
            ReworkCycle(rework_cycle_id="W2", source_review_id="R2", status="implementation_complete"),
        ]
    )
    cycle = ReviewCycle(
        review_id="R3",
        source="rework",
        source_rework_cycle_id="W2",
        agent_review=AgentReview(
            review_id="R3",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="still not correct",
        ),
        status="needs_fixes",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R3"

    monkeypatch.setattr(
        "orchestration.routing.get_config",
        lambda: type("Cfg", (), {"max_rework_cycles": 2})(),
    )

    assert route_after_agent_review(dump_pipeline_state(state)) == "human_review"


def test_route_after_agent_review_step_advances_to_escalation_when_high_risk():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="escalate",
            risk="high",
            summary="uncertain",
        ),
        status="in_review",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_agent_review(dump_pipeline_state(state)) == "escalation_review"


def test_route_after_agent_review_extra_files_do_not_override_needs_fixes():
    state = _base_state(execution_mode="workflow")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="scope pending",
        ),
        extra_changed_files=[
            ExtraChangedFile(
                path="orchestration/cli.py",
                reason="Pipeline support change.",
                reason_source="builder",
            )
        ],
        status="scope_gate_pending",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_agent_review(dump_pipeline_state(state)) == "rework_analysis"


def test_route_after_escalation_review_step_advances_to_human_review():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        escalation_review=AgentReview(
            review_id="R1",
            model_name="reviewer_escalation",
            decision="approved",
            risk="medium",
            summary="approved after escalation",
        ),
        status="approved",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_escalation_review(dump_pipeline_state(state)) == "human_review"


def test_route_after_escalation_review_needs_fixes_goes_to_rework():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        escalation_review=AgentReview(
            review_id="R1",
            model_name="reviewer_escalation",
            decision="needs_fixes",
            risk="medium",
            summary="needs targeted fixes",
        ),
        status="needs_fixes",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_escalation_review(dump_pipeline_state(state)) == "rework_analysis"


def test_route_after_escalation_review_needs_fixes_goes_to_human_review_after_max_reworks(
    monkeypatch,
):
    state = _base_state(execution_mode="workflow")
    state.rework_cycles.extend(
        [
            ReworkCycle(rework_cycle_id="W1", source_review_id="R1", status="implementation_complete"),
            ReworkCycle(rework_cycle_id="W2", source_review_id="R2", status="implementation_complete"),
        ]
    )
    cycle = ReviewCycle(
        review_id="R3",
        source="rework",
        source_rework_cycle_id="W2",
        escalation_review=AgentReview(
            review_id="R3",
            model_name="reviewer_escalation",
            decision="needs_fixes",
            risk="medium",
            summary="still not correct",
        ),
        status="needs_fixes",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R3"

    monkeypatch.setattr(
        "orchestration.routing.get_config",
        lambda: type("Cfg", (), {"max_rework_cycles": 2})(),
    )

    assert route_after_escalation_review(dump_pipeline_state(state)) == "human_review"


def test_route_after_rework_analysis_step_advances_to_rework_implementation():
    state = _base_state(execution_mode="step")
    cycle = ReworkCycle(
        rework_cycle_id="W1",
        source_review_id="R1",
        analysis=ReworkAnalysis(
            rework_cycle_id="W1",
            review_id="R1",
            root_cause="missing follow-through",
            findings_addressed=["fix the issue"],
            planned_changes=["apply the fix"],
            validation_plan=["rerun checks"],
            unresolved_assumptions=[],
            answer_matrix=[],
        ),
        status="analysis_complete",
    )
    state.rework_cycles.append(cycle)
    state.active_rework_cycle_id = "W1"

    assert route_after_rework_analysis(dump_pipeline_state(state)) == "rework_implementation"


def test_route_after_rework_implementation_step_advances_to_agent_review():
    state = _base_state(execution_mode="step")
    cycle = ReworkCycle(
        rework_cycle_id="W1",
        source_review_id="R1",
        status="implementation_complete",
    )
    state.rework_cycles.append(cycle)
    state.active_rework_cycle_id = "W1"

    assert route_after_rework_implementation(dump_pipeline_state(state)) == "agent_review"


def test_route_after_rework_implementation_blocked_ends():
    state = _base_state(execution_mode="step")
    cycle = ReworkCycle(
        rework_cycle_id="W1",
        source_review_id="R1",
        status="blocked",
    )
    state.rework_cycles.append(cycle)
    state.active_rework_cycle_id = "W1"

    assert route_after_rework_implementation(dump_pipeline_state(state)) == "__end__"


def test_route_after_rework_implementation_scope_gate_pending_goes_to_human_review():
    state = _base_state(execution_mode="step")
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            status="blocked",
        )
    )
    state.active_rework_cycle_id = "W1"
    state.review_cycles.append(
        ReviewCycle(
            review_id="R2",
            source="rework",
            source_rework_cycle_id="W1",
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
    state.active_review_cycle_id = "R2"

    assert route_after_rework_implementation(dump_pipeline_state(state)) == "human_review"


def test_graph_declares_branch_for_rework_scope_gate_human_review_route():
    state = _base_state(execution_mode="step")
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            status="blocked",
        )
    )
    state.active_rework_cycle_id = "W1"
    state.review_cycles.append(
        ReviewCycle(
            review_id="R2",
            source="rework",
            source_rework_cycle_id="W1",
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
    state.active_review_cycle_id = "R2"

    branch = route_after_rework_implementation(dump_pipeline_state(state))
    assert branch == "human_review"

    graph = build_graph(InMemorySaver())
    rework_branches = graph.builder.branches["rework_implementation"]
    route_spec = next(iter(rework_branches.values()))
    assert route_spec.ends is not None
    assert branch in route_spec.ends


def test_route_after_human_review_to_ship():
    state = _base_state()
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="approved",
            risk="low",
            summary="ok",
        ),
        human_review=HumanReview(
            review_id="R1",
            decision="approved",
            reviewer="Hitesh",
            notes="ok",
        ),
        status="approved",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_human_review(dump_pipeline_state(state)) == "ship"


def test_route_after_human_review_scope_approved_reenters_agent_review_in_workflow():
    state = _base_state()
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="scope pending",
        ),
        extra_changed_files=[
            ExtraChangedFile(
                path="orchestration/cli.py",
                reason="Pipeline support change.",
                reason_source="builder",
            )
        ],
        extra_files_review=HumanDecision(
            gate_type="extra_files_approval",
            decision="approved",
            reviewer="Hitesh",
            notes="This support change is acceptable.",
        ),
        status="scope_approved",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_human_review(dump_pipeline_state(state)) == "agent_review"


def test_route_after_human_review_scope_approved_ends_in_step_mode():
    state = _base_state(execution_mode="step")
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="scope pending",
        ),
        extra_changed_files=[
            ExtraChangedFile(
                path="orchestration/cli.py",
                reason="Pipeline support change.",
                reason_source="builder",
            )
        ],
        extra_files_review=HumanDecision(
            gate_type="extra_files_approval",
            decision="approved",
            reviewer="Hitesh",
            notes="This support change is acceptable.",
        ),
        status="scope_approved",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_human_review(dump_pipeline_state(state)) == "agent_review"


def test_route_after_human_review_to_rework():
    state = _base_state()
    cycle = ReviewCycle(
        review_id="R1",
        source="build",
        agent_review=AgentReview(
            review_id="R1",
            model_name="reviewer",
            decision="needs_fixes",
            risk="medium",
            summary="needs work",
        ),
        human_review=HumanReview(
            review_id="R1",
            decision="approved",
            reviewer="Hitesh",
            notes="still problems",
        ),
        status="needs_fixes",
    )
    state.review_cycles.append(cycle)
    state.active_review_cycle_id = "R1"

    assert route_after_human_review(dump_pipeline_state(state)) == "rework_analysis"

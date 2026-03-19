from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.review import HumanDecision, ReviewCycle, AgentReview, HumanReview
from orchestration.routing import route_after_human_review
from orchestration.state import dump_pipeline_state


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
        execution_mode="workflow",
    )


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
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.review import AgentReview, HumanReview, ReviewCycle
from orchestration.models.rework import ReworkAnalysis, ReworkCycle
from orchestration.prompts.review import build_review_prompt
from orchestration.prompts.rework import build_rework_analysis_prompt


def _base_state() -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="118",
            slug="risk-and-test-pipeline",
            title="Issue 118",
            task_file="tasks/issue-118-risk-and-test-pipeline.md",
            repo_root=".",
            branch="issue-118-risk-and-test-pipeline",
        )
    )


def test_rework_analysis_prompt_includes_review_findings_and_human_input():
    state = _base_state()
    state.review_cycles.append(
        ReviewCycle(
            review_id="R4",
            source="rework",
            agent_review=AgentReview(
                review_id="R4",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Feature is still incorrect.",
                findings=["Fix the dashboard SQL grouping bug."],
                test_gaps=["Add regression test for grouped ETH derivatives."],
            ),
            human_review=HumanReview(
                review_id="R4",
                decision="approved",
                reviewer="Hitesh",
                notes="Proceed with another rework pass.",
                response_requirements=["Address the SQL bug first."],
                unresolved_comments=["Double-counting risk still looks unresolved."],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R4"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R3",
            analysis=ReworkAnalysis(
                rework_cycle_id="W1",
                review_id="R3",
                root_cause="Earlier pass had no review context.",
                findings_addressed=["Missing test coverage."],
                planned_changes=["Update tests."],
                validation_plan=["Run backend tests."],
                unresolved_assumptions=[],
                answer_matrix=[],
            ),
            status="implementation_complete",
        )
    )

    prompt = build_rework_analysis_prompt(state)

    assert "Fix the dashboard SQL grouping bug." in prompt
    assert "Add regression test for grouped ETH derivatives." in prompt
    assert "Proceed with another rework pass." in prompt
    assert "Address the SQL bug first." in prompt
    assert "Double-counting risk still looks unresolved." in prompt
    assert "W1: status=implementation_complete" in prompt


def test_review_prompt_forbids_ungrounded_git_history_claims():
    state = _base_state()
    state.build_output = type(
        "BuildOutputStub",
        (),
        {
            "summary": "Implemented feature",
            "verification": None,
            "changed_files": ["api/app/routers/dashboard.py", "web/src/App.tsx"],
        },
    )()

    prompt = build_review_prompt(state)

    assert "Do not claim anything about git history" in prompt
    assert "api/app/routers/dashboard.py" in prompt
    assert "web/src/App.tsx" in prompt


def test_review_prompt_carries_forward_human_requirements_from_source_review():
    state = _base_state()
    state.build_output = type(
        "BuildOutputStub",
        (),
        {
            "summary": "Implemented rework",
            "verification": None,
            "changed_files": ["api/app/routers/dashboard.py"],
        },
    )()
    state.review_cycles.append(
        ReviewCycle(
            review_id="R6",
            source="rework",
            agent_review=AgentReview(
                review_id="R6",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Stock and crypto got mixed together.",
                findings=["Do not show crypto on the stock detail page."],
                test_gaps=["Add a detail-page regression test."],
            ),
            human_review=HumanReview(
                review_id="R6",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Keep stock and crypto detail pages separate.",
                response_requirements=["Verify /holdings stays stock-only after rework."],
                unresolved_comments=["Combining is only intended for dashboard risk."],
            ),
            status="needs_fixes",
        )
    )
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W4",
            source_review_id="R6",
            status="implementation_complete",
        )
    )
    state.active_rework_cycle_id = "W4"

    prompt = build_review_prompt(state)

    assert "source_review_id: R6" in prompt
    assert "Keep stock and crypto detail pages separate." in prompt
    assert "Verify /holdings stays stock-only after rework." in prompt
    assert "Combining is only intended for dashboard risk." in prompt
    assert "explicitly verify whether the source review's human response requirements" in prompt

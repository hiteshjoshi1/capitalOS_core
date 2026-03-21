from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.review import AgentReview, HumanDecision, HumanReview, ReviewCycle
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


def test_rework_analysis_prompt_preserves_source_review_intent_through_scope_gate():
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
                summary="Docs are stale.",
                findings=["Fix ReadMe.md and ai-task-flow.md using current Makefile commands."],
                test_gaps=["Verify task-respond is documented."],
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Update docs to the LangGraph workflow and keep the template aligned.",
                response_requirements=["Keep the docs aligned with the latest orchestration flow."],
            ),
            status="needs_fixes",
        )
    )
    state.review_cycles.append(
        ReviewCycle(
            review_id="R2",
            source="rework",
            agent_review=AgentReview(
                review_id="R2",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Scope approval required first.",
                findings=["Unapproved extra changed files were detected outside the planned paths."],
                test_gaps=[],
            ),
            extra_changed_files=[
                {
                    "path": "tasks/_template.md",
                    "reason": "Builder could not infer why this out-of-scope file was changed.",
                    "reason_source": "unknown",
                }
            ],
            extra_files_review=HumanDecision.model_validate(
                {
                    "gate_type": "extra_files_approval",
                    "decision": "needs_fixes",
                    "reviewer": "Hitesh",
                    "notes": "Template is okay, but the main docs still need fixing.",
                    "response_requirements": ["Document task-respond and current stage commands."],
                    "unresolved_comments": ["Do not lose the main documentation objective."],
                }
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R2"

    prompt = build_rework_analysis_prompt(state)

    assert "active_review_id: R2" in prompt
    assert "review_id: R1" in prompt
    assert "Fix ReadMe.md and ai-task-flow.md using current Makefile commands." in prompt
    assert "Update docs to the LangGraph workflow and keep the template aligned." in prompt
    assert "Template is okay, but the main docs still need fixing." in prompt
    assert "Document task-respond and current stage commands." in prompt
    assert "Do not lose the main documentation objective." in prompt
    assert "preserve the main task intent from the source review" in prompt


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


def test_review_prompt_includes_semantic_requirements_and_grounded_verification_rules():
    state = _base_state()
    state.plan_output = type(
        "PlanOutputStub",
        (),
        {
            "summary": "Fix workflow docs",
            "acceptance_criteria": [
                "ai-task-flow.md documents the interactive human-gate flow correctly."
            ],
        },
    )()
    state.build_output = type(
        "BuildOutputStub",
        (),
        {
            "summary": "Updated docs",
            "verification": None,
            "changed_files": ["docs/workflows/ai-task-flow.md"],
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
                summary="Docs are still wrong.",
                findings=["Document the real interactive command."],
                test_gaps=[],
                semantic_verification=["Acceptance criterion not yet proven against Makefile and CLI."],
            ),
            human_review=HumanReview(
                review_id="R6",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Use the real Makefile behavior.",
                response_requirements=["Describe task-respond as the primary interactive gate command."],
                unresolved_comments=["Do not present JSON resume commands as the default operator path."],
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

    assert "Semantic requirements to verify against implementation:" in prompt
    assert "Acceptance criterion: ai-task-flow.md documents the interactive human-gate flow correctly." in prompt
    assert "Human response requirement: Describe task-respond as the primary interactive gate command." in prompt
    assert "Human unresolved concern: Do not present JSON resume commands as the default operator path." in prompt
    assert '"semantic_verification": ["string"]' in prompt
    assert "Perform a grounded semantic verification pass against the implementation" in prompt
    assert "compare the docs against the real implementation sources" in prompt


def test_rework_prompts_carry_semantic_requirements_forward():
    state = _base_state()
    state.plan_output = type(
        "PlanOutputStub",
        (),
        {
            "summary": "Fix workflow docs",
            "acceptance_criteria": [
                "ai-task-flow.md documents the interactive human-gate flow correctly."
            ],
        },
    )()
    state.review_cycles.append(
        ReviewCycle(
            review_id="R7",
            source="rework",
            agent_review=AgentReview(
                review_id="R7",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Docs still mismatch behavior.",
                findings=["Update the respond command semantics."],
                test_gaps=["Add a documentation accuracy check."],
                semantic_verification=[
                    "ReadMe.md still treats JSON resume commands as the default gate path."
                ],
            ),
            human_review=HumanReview(
                review_id="R7",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Fix the docs semantically, not just by adding the command name.",
                response_requirements=["Describe task-respond as an interactive human gate."],
                unresolved_comments=["Do not stop at string presence."],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R7"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W5",
            source_review_id="R7",
            status="analysis_complete",
        )
    )
    state.active_rework_cycle_id = "W5"

    analysis_prompt = build_rework_analysis_prompt(state)

    assert "Source review semantic verification:" in analysis_prompt
    assert "ReadMe.md still treats JSON resume commands as the default gate path." in analysis_prompt
    assert "Semantic requirements that must be satisfied end-to-end:" in analysis_prompt
    assert "Acceptance criterion: ai-task-flow.md documents the interactive human-gate flow correctly." in analysis_prompt
    assert "Human response requirement: Describe task-respond as an interactive human gate." in analysis_prompt
    assert "Treat the semantic requirements above as mandatory" in analysis_prompt

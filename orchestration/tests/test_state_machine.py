from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.build import RetryEntry
from orchestration.models.review import AgentReview, HumanDecision, HumanReview, ReviewCycle


def test_next_review_and_rework_ids():
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="1",
            slug="x",
            title="x",
            task_file="tasks/issue-1-x.md",
            repo_root=".",
            branch="feature/issue-1-x",
        )
    )
    assert state.next_review_id() == "R1"
    assert state.next_rework_id() == "W1"


def test_retry_entry_accumulates():
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="1",
            slug="x",
            title="x",
            task_file="tasks/issue-1-x.md",
            repo_root=".",
            branch="feature/issue-1-x",
        )
    )
    entry = RetryEntry(
        label="lint",
        attempt=1,
        max_attempts=3,
        command="make lint",
        exit_code=2,
        classification="code",
    )
    state.add_retry(entry)
    assert len(state.retry_log) == 1
    assert state.retry_log[0].label == "lint"


def test_get_rework_context_review_cycle_prefers_latest_substantive_review_over_scope_gate():
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="1",
            slug="x",
            title="x",
            task_file="tasks/issue-1-x.md",
            repo_root=".",
            branch="issue-1-x",
        )
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
                summary="Fix the docs.",
                findings=["Update ReadMe.md and ai-task-flow.md."],
                test_gaps=[],
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
            extra_changed_files=[{"path": "tasks/_template.md", "reason": "unknown", "reason_source": "unknown"}],
            extra_files_review=HumanDecision(
                gate_type="extra_files_approval",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Keep fixing the docs too.",
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R2"

    context_cycle = state.get_rework_context_review_cycle()

    assert context_cycle is not None
    assert context_cycle.review_id == "R1"


def test_get_semantic_requirements_merges_acceptance_and_human_guidance():
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="1",
            slug="x",
            title="x",
            task_file="tasks/issue-1-x.md",
            repo_root=".",
            branch="issue-1-x",
        )
    )
    state.plan_output = type(
        "PlanOutputStub",
        (),
        {
            "acceptance_criteria": [
                "Document the interactive review flow correctly.",
                "Document the interactive review flow correctly.",
            ]
        },
    )()
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer",
                decision="needs_fixes",
                risk="medium",
                summary="Fix docs",
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Fix semantics",
                response_requirements=["Describe task-respond as the primary human-gate command."],
                unresolved_comments=["Do not rely on string presence alone."],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"

    requirements = state.get_semantic_requirements()

    assert requirements == [
        "Acceptance criterion: Document the interactive review flow correctly.",
        "Human response requirement: Describe task-respond as the primary human-gate command.",
        "Human unresolved concern: Do not rely on string presence alone.",
    ]

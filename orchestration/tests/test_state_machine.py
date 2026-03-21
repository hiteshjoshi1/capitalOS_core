from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.build import RetryEntry


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
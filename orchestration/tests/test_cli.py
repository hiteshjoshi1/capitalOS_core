from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

from orchestration.cli import (
    _pipeline_with_interrupt_context,
    build_interactive_resume_payload,
    load_pending_interrupt,
    make_step_state,
)
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.review import HumanDecision


class _FakeGraph:
    def __init__(self, pipeline: dict | None, history: list[dict] | None = None, interrupts: list | None = None) -> None:
        self._pipeline = pipeline
        self._history = history or []
        self._interrupts = interrupts or []

    def get_state(self, config):
        return SimpleNamespace(
            values={"pipeline": self._pipeline} if self._pipeline is not None else {},
            interrupts=self._interrupts,
            next=(),
        )

    def get_state_history(self, config):
        return [SimpleNamespace(values={"pipeline": pipeline}) for pipeline in self._history]


def _args() -> Namespace:
    return Namespace(
        issue_id=None,
        slug=None,
        title=None,
        task_file="tasks/issue-118-risk-and-test-pipeline.md",
        repo_root=".",
    )


def test_make_step_state_reuses_existing_pipeline_state() -> None:
    pipeline = PipelineState(
        issue=IssueMetadata(
            issue_id="118",
            slug="risk-and-test-pipeline",
            title="Risk And Test Pipeline",
            task_file="tasks/issue-118-risk-and-test-pipeline.md",
            repo_root="/tmp/repo",
            branch="feature/issue-118-risk-and-test-pipeline",
        ),
        current_stage="human_approval_gate",
        workflow_status="running",
        requested_entrypoint="plan",
        execution_mode="step",
        plan_output=PlanOutput(
            summary="Planned",
            architecture_decisions=["A"],
            risks=["R"],
            open_questions=[],
            acceptance_criteria=["AC1"],
            planned_paths=["orchestration/"],
            checklist=[],
        ),
        human_gate_decisions={
            "plan_approval": HumanDecision(
                gate_type="plan_approval",
                decision="approved",
                reviewer="Hitesh",
                notes="Approved",
            )
        },
    )

    graph = _FakeGraph(pipeline.model_dump(mode="json"))
    state = make_step_state(_args(), "build", graph, {"configurable": {"thread_id": "issue-118"}})

    reused = PipelineState.model_validate(state["pipeline"])
    assert reused.requested_entrypoint == "build"
    assert reused.execution_mode == "step"
    assert reused.human_gate_decisions["plan_approval"].decision == "approved"
    assert reused.plan_output is not None


def test_make_step_state_bootstraps_when_thread_has_no_state() -> None:
    graph = _FakeGraph(None)
    state = make_step_state(_args(), "build", graph, {"configurable": {"thread_id": "issue-118"}})

    bootstrapped = PipelineState.model_validate(state["pipeline"])
    assert bootstrapped.requested_entrypoint == "build"
    assert bootstrapped.execution_mode == "step"
    assert bootstrapped.plan_output is None
    assert bootstrapped.human_gate_decisions == {}


def test_make_step_state_ignores_latest_blank_checkpoint_and_recovers_approved_state() -> None:
    approved = PipelineState(
        issue=IssueMetadata(
            issue_id="118",
            slug="risk-and-test-pipeline",
            title="Risk And Test Pipeline",
            task_file="tasks/issue-118-risk-and-test-pipeline.md",
            repo_root="/tmp/repo",
            branch="feature/issue-118-risk-and-test-pipeline",
        ),
        current_stage="human_approval_gate",
        workflow_status="running",
        requested_entrypoint="plan",
        execution_mode="step",
        plan_output=PlanOutput(
            summary="Planned",
            architecture_decisions=["A"],
            risks=["R"],
            open_questions=[],
            acceptance_criteria=["AC1"],
            planned_paths=["orchestration/"],
            checklist=[],
        ),
        human_gate_decisions={
            "plan_approval": HumanDecision(
                gate_type="plan_approval",
                decision="approved",
                reviewer="Hitesh",
                notes="Approved",
            )
        },
    )
    blank_latest = PipelineState(
        issue=approved.issue,
        requested_entrypoint="build",
        execution_mode="step",
    )

    graph = _FakeGraph(
        blank_latest.model_dump(mode="json"),
        history=[blank_latest.model_dump(mode="json"), approved.model_dump(mode="json")],
    )

    state = make_step_state(_args(), "build", graph, {"configurable": {"thread_id": "issue-118"}})
    recovered = PipelineState.model_validate(state["pipeline"])

    assert recovered.requested_entrypoint == "build"
    assert recovered.human_gate_decisions["plan_approval"].decision == "approved"
    assert recovered.plan_output is not None


def test_load_pending_interrupt_returns_first_interrupt() -> None:
    graph = _FakeGraph(
        None,
        interrupts=[
            SimpleNamespace(
                value={
                    "gate": "extra_files_approval",
                    "review_id": "R1",
                }
            )
        ],
    )

    interrupt = load_pending_interrupt(graph, {"configurable": {"thread_id": "issue-118"}})

    assert interrupt["gate"] == "extra_files_approval"


def test_pipeline_with_interrupt_context_overrides_stage_for_human_review_gate() -> None:
    pipeline = PipelineState(
        issue=IssueMetadata(
            issue_id="118",
            slug="risk-and-test-pipeline",
            title="Risk And Test Pipeline",
            task_file="tasks/issue-118-risk-and-test-pipeline.md",
            repo_root="/tmp/repo",
            branch="feature/issue-118-risk-and-test-pipeline",
        ),
        current_stage="rework_analysis",
        workflow_status="running",
    )
    snapshot = SimpleNamespace(
        values={"pipeline": pipeline.model_dump(mode="json")},
        interrupts=[SimpleNamespace(value={"gate": "human_review", "review_id": "R6"})],
        next=("human_review",),
    )

    effective = _pipeline_with_interrupt_context(snapshot)

    assert effective is not None
    assert effective.current_stage == "human_review"
    assert effective.workflow_status == "waiting_for_human"


def test_build_interactive_resume_payload_for_approval() -> None:
    answers = iter(
        [
            "y",
            "Hitesh",
            "Looks good.",
            "",
        ]
    )
    payload = build_interactive_resume_payload(
        {"gate": "human_review", "review_id": "R1", "agent_review": {"decision": "approved", "summary": "ok"}},
        input_fn=lambda prompt: next(answers),
        print_fn=lambda message: None,
    )

    assert payload == {
        "gate_type": "human_review",
        "decision": "approved",
        "reviewer": "Hitesh",
        "notes": "Looks good.",
        "questions": [],
        "response_requirements": [],
        "unresolved_comments": [],
    }


def test_build_interactive_resume_payload_for_needs_fixes() -> None:
    answers = iter(
        [
            "n",
            "Hitesh",
            "Please fix the scope issue.",
            "Was SQLite considered? | Why was cash included?",
            "Use SQLite-safe SQL | update the failing risk-card assertion",
            "Do not ship until tests pass | explain extra file changes",
        ]
    )
    payload = build_interactive_resume_payload(
        {"gate": "extra_files_approval", "extra_changed_files": [{"path": ".gitignore", "reason": "ignore task-flow"}]},
        input_fn=lambda prompt: next(answers),
        print_fn=lambda message: None,
    )

    assert payload == {
        "gate_type": "extra_files_approval",
        "decision": "needs_fixes",
        "reviewer": "Hitesh",
        "notes": "Please fix the scope issue.",
        "questions": ["Was SQLite considered?", "Why was cash included?"],
        "response_requirements": ["Use SQLite-safe SQL", "update the failing risk-card assertion"],
        "unresolved_comments": ["Do not ship until tests pass", "explain extra file changes"],
    }


def test_build_interactive_resume_payload_prompts_for_response_requirements() -> None:
    answers = iter(
        [
            "n",
            "Hitesh",
            "Please address the regression.",
            "",
            "Keep /holdings stock-only | Verify /crypto/holdings stays crypto-only",
            "Do not merge stock and crypto detail pages",
        ]
    )
    prompts: list[str] = []
    output: list[str] = []

    payload = build_interactive_resume_payload(
        {"gate": "human_review", "review_id": "R7", "agent_review": {"decision": "approved", "summary": "Looks good"}},
        input_fn=lambda prompt: prompts.append(prompt) or next(answers),
        print_fn=lambda message: output.append(message),
    )

    assert "What must be addressed before approval?" in output
    assert any("Response requirements for the next rework/review" in prompt for prompt in prompts)
    assert payload["response_requirements"] == [
        "Keep /holdings stock-only",
        "Verify /crypto/holdings stays crypto-only",
    ]

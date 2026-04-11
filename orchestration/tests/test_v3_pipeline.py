from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from orchestration.graph import build_graph
from orchestration.models.build import ExtraChangedFile
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.routing import (
    route_after_agent_run,
    route_after_deterministic_gates,
    route_after_plan,
    route_after_prepare,
)
from orchestration.services.config import ModelRoutingConfig
from orchestration.services.v3_policy import V3PolicyService
from orchestration.state import dump_pipeline_state


def _state() -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="126",
            slug="v3",
            title="V3",
            task_file="tasks/issue-126-v3.md",
            repo_root=".",
            branch="feature/issue-126-v3",
        ),
        pipeline_version="v3",
    )


def test_route_after_prepare_v3_goes_to_agent_run() -> None:
    state = _state()
    assert route_after_prepare(dump_pipeline_state(state)) == "agent_run"


def test_graph_declares_prepare_branch_for_v3_agent_run() -> None:
    branch = route_after_prepare(dump_pipeline_state(_state()))
    assert branch == "agent_run"

    graph = build_graph(InMemorySaver())
    prepare_branches = graph.builder.branches["prepare"]
    route_spec = next(iter(prepare_branches.values()))
    assert route_spec.ends is not None
    assert branch in route_spec.ends


def test_graph_declares_plan_branch_for_v3_agent_run() -> None:
    branch = route_after_plan(dump_pipeline_state(_state()))
    assert branch == "agent_run"

    graph = build_graph(InMemorySaver())
    plan_branches = graph.builder.branches["plan"]
    route_spec = next(iter(plan_branches.values()))
    assert route_spec.ends is not None
    assert branch in route_spec.ends


def test_route_after_agent_run_blocked_ends() -> None:
    state = _state()
    state.workflow_status = "blocked"
    assert route_after_agent_run(dump_pipeline_state(state)) == "__end__"


def test_route_after_agent_run_success_goes_to_deterministic_gates() -> None:
    state = _state()
    state.workflow_status = "running"
    assert route_after_agent_run(dump_pipeline_state(state)) == "deterministic_gates"


def test_route_after_deterministic_gates_waiting_for_human_ends() -> None:
    state = _state()
    state.workflow_status = "waiting_for_human"
    assert route_after_deterministic_gates(dump_pipeline_state(state)) == "__end__"


def test_route_after_deterministic_gates_blocked_ends() -> None:
    state = _state()
    state.workflow_status = "blocked"
    assert route_after_deterministic_gates(dump_pipeline_state(state)) == "__end__"


def test_route_after_deterministic_gates_running_goes_to_ship() -> None:
    # "running" is not a normal v3 outcome from deterministic_gates but still routes to ship
    state = _state()
    state.workflow_status = "running"
    assert route_after_deterministic_gates(dump_pipeline_state(state)) == "ship"


def test_v3_policy_blocks_restricted_and_missing_reason(tmp_path) -> None:
    service = V3PolicyService(str(tmp_path))
    result = service.evaluate(
        changed_files=[".gitignore", "web/src/App.tsx"],
        allowed_paths=["tasks/issue-126-v3.md"],
        extra_changed_files=[],
    )
    assert result.blocked is True
    assert any("Restricted file modified" in item for item in result.blockers)
    assert any("missing explicit reason" in item for item in result.blockers)


def test_v3_policy_accepts_reasoned_out_of_scope_file(tmp_path) -> None:
    service = V3PolicyService(str(tmp_path))
    result = service.evaluate(
        changed_files=["web/src/App.tsx"],
        allowed_paths=["tasks/issue-126-v3.md"],
        extra_changed_files=[
            ExtraChangedFile(
                path="web/src/App.tsx",
                reason="Needed for shared route wiring in this task.",
                reason_source="builder",
            )
        ],
    )
    assert result.blocked is False
    assert len(result.extra_files_with_reasons) == 1


def test_model_routing_config_supports_v3_fields() -> None:
    cfg = ModelRoutingConfig(
        pipeline_version="v3",
        v3_provider="codex",
        v3_model="gpt-5.3-codex",
    )
    assert cfg.pipeline_version == "v3"
    assert cfg.v3_provider == "codex"
    assert cfg.v3_model == "gpt-5.3-codex"

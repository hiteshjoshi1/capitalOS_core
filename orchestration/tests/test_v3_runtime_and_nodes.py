from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestration.models.agent_run import AgentRunOutput
from orchestration.models.build import ExtraChangedFile
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.verification import VerificationCommandResult, VerificationEvidence
from orchestration.nodes import agent_run as agent_run_node
from orchestration.nodes import deterministic_gates as deterministic_gates_node
from orchestration.services.deterministic_fix import DeterministicFixService
from orchestration.services.provider_runtime import ProviderRunResult, ProviderRuntimeService
from orchestration.services.v3_policy import V3PolicyResult


def _task_file(tmp_path: Path, rel_path: str) -> None:
    path = tmp_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Issue 126: Test",
                "",
                "## Objective",
                "- test",
                "",
                "<!-- IMMUTABLE_PLAN_END -->",
                "",
                "<!-- MACHINE_RENDERED_START -->",
                "## Execution Journal",
                "_Not rendered yet._",
                "<!-- MACHINE_RENDERED_END -->",
            ]
        )
    )


def _agent_output() -> AgentRunOutput:
    return AgentRunOutput(
        summary="Implemented changes.",
        plan_summary="Plan done.",
        architecture_decisions=["Keep v3 deterministic."],
        risks=["None"],
        open_questions=[],
        acceptance_criteria=["AC1"],
        planned_paths=["web/src/"],
        checklist=[],
        changed_files=["web/src/App.tsx"],
        extra_changed_files=[],
        implementation_notes=["Implemented."],
        acceptance_criteria_checks=[
            {"criterion": "AC1", "status": "pass", "evidence": "Updated UI and tests."}
        ],
        semantic_intent_achieved=True,
        risk_flags=[],
    )


def _v3_state(tmp_path: Path) -> PipelineState:
    task = "tasks/issue-126-v3.md"
    _task_file(tmp_path, task)
    return PipelineState(
        issue=IssueMetadata(
            issue_id="126",
            slug="v3",
            title="V3",
            task_file=task,
            repo_root=str(tmp_path),
            branch="feature/issue-126-v3",
        ),
        pipeline_version="v3",
    )


def test_agent_run_success_populates_plan_and_provider(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)

    def fake_complete_structured(self, prompt, model_cls):
        _ = (self, prompt, model_cls)
        return _agent_output(), ProviderRunResult(
            provider="copilot",
            model="gpt-5.3-codex",
            output="{}",
            diagnostics=[],
        )

    monkeypatch.setattr(
        "orchestration.nodes.agent_run.ProviderRuntimeService.complete_structured",
        fake_complete_structured,
    )

    result = agent_run_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "running"
    assert pipeline.agent_run_output is not None
    assert pipeline.plan_output is not None
    assert pipeline.plan_output.immutable_plan_hash is not None
    assert pipeline.v3_provider == "copilot"
    assert pipeline.v3_model == "gpt-5.3-codex"


def test_agent_run_failure_blocks_with_reason(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)

    def fake_complete_structured(self, prompt, model_cls):
        _ = (self, prompt, model_cls)
        raise RuntimeError("provider crashed")

    monkeypatch.setattr(
        "orchestration.nodes.agent_run.ProviderRuntimeService.complete_structured",
        fake_complete_structured,
    )

    result = agent_run_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert pipeline.v3_permanent_failure_reason is not None
    assert "agent_run failed" in pipeline.v3_permanent_failure_reason


def _verification_pass() -> VerificationEvidence:
    return VerificationEvidence(
        results=[
            VerificationCommandResult(
                name="lint",
                command="make lint",
                status="pass",
                exit_code=0,
                output_excerpt="ok",
            )
        ],
        any_failures=False,
    )


def _verification_fail() -> VerificationEvidence:
    return VerificationEvidence(
        results=[
            VerificationCommandResult(
                name="test-frontend",
                command="make test-frontend",
                status="fail",
                exit_code=2,
                output_excerpt="failed",
            )
        ],
        any_failures=True,
    )


def _patch_deterministic_deps(monkeypatch, *, verification: VerificationEvidence, policy: V3PolicyResult):
    monkeypatch.setattr(deterministic_gates_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.VerificationService.run_default_suite",
        lambda self, max_attempts=3, on_code_retry_fix=None: (verification, []),
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.ScopePolicyService.review_allowed_paths",
        lambda self: ["web/src/"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.V3PolicyService.evaluate",
        lambda self, changed_files, allowed_paths, extra_changed_files: policy,
    )


def test_deterministic_gates_success(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_auto_fix_mode="deterministic_only",
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_pass(), policy=V3PolicyResult(blocked=False))

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "running"
    assert pipeline.build_output is not None
    assert pipeline.blockers == []


def test_deterministic_gates_schedules_single_repair_session(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_auto_fix_mode="single_repair_session",
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_fail(), policy=V3PolicyResult(blocked=False))

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "needs_fixes"
    assert pipeline.v3_repair_session_used is True


def test_deterministic_gates_blocks_when_policy_fails(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_auto_fix_mode="deterministic_only",
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(
        monkeypatch,
        verification=_verification_pass(),
        policy=V3PolicyResult(blocked=True, blockers=["Restricted file modified: `.gitignore`."]),
    )

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "blocked"
    assert "Restricted file modified: `.gitignore`." in pipeline.blockers


def test_deterministic_gates_high_risk_rejected_blocks(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    output = _agent_output()
    output.risk_flags = ["Potential secret exposure."]
    state.agent_run_output = output

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_auto_fix_mode="deterministic_only",
            v3_require_pre_ship_human_on_high_risk=True,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_pass(), policy=V3PolicyResult(blocked=False))
    monkeypatch.setattr(
        deterministic_gates_node,
        "interrupt",
        lambda payload: {
            "gate_type": "v3_high_risk_review",
            "decision": "needs_fixes",
            "reviewer": "Hitesh",
            "notes": "Risk too high.",
        },
    )

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "blocked"
    assert "High-risk findings rejected" in pipeline.blockers[0]


def test_provider_runtime_complete_structured_fallback(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_provider="copilot",
        v3_model="gpt-5.3-codex",
        v3_enable_provider_fallback=True,
        v3_fallback_provider="codex",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    calls: list[str] = []

    def fake_run_provider(self, provider, *, model, prompt):
        _ = (self, model, prompt)
        calls.append(provider)
        if provider == "copilot":
            raise RuntimeError("primary failed")
        payload = {
            "summary": "ok",
            "plan_summary": "plan",
            "architecture_decisions": [],
            "risks": [],
            "open_questions": [],
            "acceptance_criteria": [],
            "planned_paths": [],
            "checklist": [],
            "changed_files": [],
            "extra_changed_files": [],
            "implementation_notes": [],
            "acceptance_criteria_checks": [],
            "semantic_intent_achieved": True,
            "risk_flags": [],
        }
        return ProviderRunResult(
            provider="codex",
            model="gpt-5.3-codex",
            output=json.dumps(payload),
            diagnostics=[],
        )

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)
    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    parsed, run_result = service.complete_structured("prompt", AgentRunOutput)

    assert parsed.summary == "ok"
    assert run_result.provider == "codex"
    assert calls == ["copilot", "codex"]


def test_provider_runtime_run_provider_dispatch_and_prefix(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=True,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_provider="copilot",
        v3_model="gpt-5.3-codex",
        v3_enable_provider_fallback=False,
        v3_fallback_provider="codex",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)
    monkeypatch.setattr("orchestration.services.provider_runtime.shutil.which", lambda _: "/usr/bin/caffeinate")

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    prefixed = service._prefix_with_caffeinate(["copilot", "--model", "x"])
    assert prefixed[:2] == ["/usr/bin/caffeinate", "-dimsu"]

    monkeypatch.setattr(service, "_run_copilot", lambda model, prompt: ProviderRunResult("copilot", model, "{}", []))
    monkeypatch.setattr(service, "_run_codex", lambda model, prompt: ProviderRunResult("codex", model, "{}", []))
    assert service._run_provider("copilot", model="m", prompt="p").provider == "copilot"
    assert service._run_provider("codex", model="m", prompt="p").provider == "codex"
    with pytest.raises(RuntimeError, match="Unsupported provider"):
        service._run_provider("other", model="m", prompt="p")


def test_provider_runtime_run_codex_uses_output_file_and_cleans_up(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_provider="codex",
        v3_model="gpt-5.3-codex",
        v3_enable_provider_fallback=False,
        v3_fallback_provider="copilot",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)
    created: dict[str, Path] = {}

    def fake_run(args, cwd, capture_output, text, timeout):
        _ = (cwd, capture_output, text, timeout)
        out_idx = args.index("--output-last-message") + 1
        output_path = Path(args[out_idx])
        output_path.write_text('{"ok": true}')
        created["path"] = output_path
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("orchestration.services.provider_runtime.subprocess.run", fake_run)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    result = service._run_codex(model="gpt-5.3-codex", prompt="do it")
    assert result.provider == "codex"
    assert result.output == '{"ok": true}'
    assert created["path"].exists() is False


def test_deterministic_fix_branches(monkeypatch, tmp_path) -> None:
    service = DeterministicFixService(str(tmp_path))

    docker = service.apply_for_failure(
        output="permission denied while trying to connect to the docker daemon socket"
    )
    assert docker.applied is False

    calls: list[str] = []
    monkeypatch.setattr(service, "_run", lambda command: calls.append(command))

    npm = service.apply_for_failure(output="command not found: npm")
    playwright = service.apply_for_failure(output="Playwright executable doesn't exist")
    mypy = service.apply_for_failure(output="mypy not installed")
    other = service.apply_for_failure(output="some random failure")

    assert npm.applied is True
    assert playwright.applied is True
    assert mypy.applied is False
    assert other.applied is False
    assert "make web-deps" in calls
    assert "cd web && npx playwright install" in calls

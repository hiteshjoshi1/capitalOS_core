from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestration.models.agent_run import AgentRunOutput, CommandExecutionCheck
from orchestration.models.build import ExtraChangedFile
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.verification import VerificationCommandResult, VerificationEvidence
from orchestration.nodes import agent_run as agent_run_node
from orchestration.nodes import deterministic_gates as deterministic_gates_node
from orchestration.prompts.agent_run import build_agent_run_prompt
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
        verification_commands_run=[
            {"command": "make lint", "status": "pass", "evidence": "ok"},
            {"command": "make typecheck", "status": "pass", "evidence": "ok"},
            {"command": "make contract-frontend", "status": "pass", "evidence": "ok"},
            {"command": "make test-frontend", "status": "pass", "evidence": "ok"},
        ],
        unresolved_failures=[],
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
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )

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


def test_agent_run_blocks_on_changed_files_mismatch(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["api/app/main.py"],
    )

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
    assert pipeline.workflow_status == "blocked"
    assert any("changed_files" in item for item in pipeline.blockers)


def test_agent_run_allows_pipeline_managed_task_file_diff(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["tasks/issue-126-v3.md", "web/src/App.tsx"],
    )

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
    assert sorted(pipeline.agent_run_output.changed_files) == ["tasks/issue-126-v3.md", "web/src/App.tsx"]


def test_agent_run_prompt_requires_exact_make_commands(tmp_path) -> None:
    state = _v3_state(tmp_path)
    prompt = build_agent_run_prompt(state)

    # Prompt must instruct the model to run the full suite, not a changed-files subset
    assert "make api-rebuild" in prompt
    assert "make lint" in prompt
    assert "make orch-test" in prompt
    assert "run the FULL suite before returning JSON" in prompt
    # Prompt must still tell the model it is not the final authority
    assert "re-run" in prompt or "re-runs" in prompt or "independently" in prompt
    # Prompt must still tell the model not to substitute raw commands
    assert "do not substitute" in prompt or "do not substitute" in prompt.lower()


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
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_pass(), policy=V3PolicyResult(blocked=False))

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "waiting_for_human"
    assert pipeline.build_output is not None
    assert pipeline.blockers == []


def test_deterministic_gates_blocks_when_verification_fails(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_fail(), policy=V3PolicyResult(blocked=False))

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    assert pipeline.workflow_status == "blocked"
    assert any("Deterministic gates failed" in item for item in pipeline.blockers)


def test_deterministic_gates_blocks_when_policy_fails(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
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


def test_provider_runtime_complete_structured_raises_on_primary_failure(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=False,
        v3_provider="copilot",
        v3_model="gpt-5.3-codex",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    calls: list[str] = []

    def fake_run_provider(self, provider, *, model, prompt):
        _ = (self, model, prompt)
        calls.append(provider)
        raise RuntimeError("primary failed")

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)
    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    with pytest.raises(RuntimeError, match="subprocess failed"):
        service.complete_structured("prompt", AgentRunOutput)

    assert calls == ["copilot"]


def test_provider_runtime_run_provider_dispatch_and_prefix(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=True,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=False,
        v3_provider="copilot",
        v3_model="gpt-5.3-codex",
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
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=False,
        v3_provider="codex",
        v3_model="gpt-5.3-codex",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)
    created: dict[str, Path] = {}

    class FakePopen:
        def __init__(self, args, cwd, stdout, stderr, text, bufsize):
            _ = (cwd, stdout, stderr, text, bufsize)
            out_idx = args.index("--output-last-message") + 1
            output_path = Path(args[out_idx])
            output_path.write_text('{"ok": true}')
            created["path"] = output_path
            self.returncode = 0
            self.stdout = StringIO("")
            self.stderr = StringIO("")

        def wait(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr("orchestration.services.provider_runtime.subprocess.Popen", FakePopen)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    result = service._run_codex(model="gpt-5.3-codex", prompt="do it")
    assert result.provider == "codex"
    assert result.output == '{"ok": true}'
    assert created["path"].exists() is False


def test_provider_runtime_run_copilot_streams_stdout(monkeypatch, tmp_path, capsys) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=False,
        v3_provider="copilot",
        v3_model="claude-sonnet-4.6",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    class FakePopen:
        def __init__(self, args, cwd, stdout, stderr, text, bufsize):
            _ = (args, cwd, stdout, stderr, text, bufsize)
            self.returncode = 0
            self.stdout = StringIO('{"ok": true}\n')
            self.stderr = StringIO("thinking...\n")

        def wait(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr("orchestration.services.provider_runtime.subprocess.Popen", FakePopen)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    result = service._run_copilot(model="claude-sonnet-4.6", prompt="do it")

    captured = capsys.readouterr()
    assert '{"ok": true}' in captured.out
    assert "thinking..." in captured.err
    assert result.output == '{"ok": true}'


def test_provider_runtime_complete_structured_uses_copilot_session_fallback(monkeypatch, tmp_path) -> None:
    cfg = SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=False,
        v3_provider="copilot",
        v3_model="claude-sonnet-4.6",
    )
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    def fake_run_provider(self, provider, *, model, prompt):
        _ = (self, provider, model, prompt)
        return ProviderRunResult(
            provider="copilot",
            model="claude-sonnet-4.6",
            output="tool chatter\npartial json {\n",
            diagnostics=["provider=copilot"],
            fallback_output='```json\n{"summary":"ok","plan_summary":"done","architecture_decisions":[],"risks":[],"open_questions":[],"acceptance_criteria":[],"planned_paths":[],"checklist":[],"changed_files":[],"extra_changed_files":[],"implementation_notes":[],"verification_commands_run":[],"unresolved_failures":[],"acceptance_criteria_checks":[],"semantic_intent_achieved":true,"risk_flags":[]}\n```',
        )

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    parsed, result = service.complete_structured("prompt", AgentRunOutput)

    assert parsed.summary == "ok"
    assert result.provider == "copilot"


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


# ---- New tests for v3 repair cycle, inactivity, and happy-path state ----

def _make_cfg(*, repair_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        v3_enable_caffeinate=False,
        build_max_autopilot_continues=3,
        v3_longrun_timeout_minutes=5,
        v3_inactivity_timeout_minutes=30,
        v3_repair_enabled=repair_enabled,
        v3_provider="copilot",
        v3_model="claude-sonnet-4.6",
    )


def _minimal_agent_output_json() -> str:
    return (
        '{"summary":"ok","plan_summary":"done","architecture_decisions":[],'
        '"risks":[],"open_questions":[],"acceptance_criteria":[],'
        '"planned_paths":[],"checklist":[],"changed_files":[],'
        '"extra_changed_files":[],"implementation_notes":[],'
        '"verification_commands_run":[],"unresolved_failures":[],'
        '"acceptance_criteria_checks":[],"semantic_intent_achieved":true,"risk_flags":[]}'
    )


def test_provider_runtime_repair_succeeds_after_malformed_output(monkeypatch, tmp_path) -> None:
    """When primary parse fails but repair produces valid JSON, complete_structured succeeds."""
    cfg = _make_cfg(repair_enabled=True)
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    events_path = tmp_path / "events.jsonl"
    events_path.write_text("")  # empty but exists

    def fake_run_provider(self, provider, *, model, prompt):
        return ProviderRunResult(
            provider="copilot",
            model=model,
            output="the model forgot to emit JSON brr",
            diagnostics=[],
            session_events_path=str(events_path),
        )

    repaired: list[str] = []

    def fake_run_copilot_repair(self, *, model, prompt):
        repaired.append(prompt)
        return _minimal_agent_output_json()

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)
    monkeypatch.setattr(ProviderRuntimeService, "_run_copilot_repair", fake_run_copilot_repair)
    monkeypatch.setattr(
        "orchestration.services.provider_runtime.extract_session_repair_context",
        lambda path: "Agent read files and wrote api/app/main.py",
    )

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    parsed, _ = service.complete_structured("do work", AgentRunOutput)

    assert parsed.summary == "ok"
    assert len(repaired) == 1
    assert "do work" in repaired[0]


def test_provider_runtime_repair_disabled_raises_on_malformed_output(monkeypatch, tmp_path) -> None:
    """When repair is disabled and output is malformed, complete_structured raises immediately."""
    cfg = _make_cfg(repair_enabled=False)
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    def fake_run_provider(self, provider, *, model, prompt):
        return ProviderRunResult(
            provider="copilot",
            model=model,
            output="not json at all",
            diagnostics=[],
        )

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    with pytest.raises(RuntimeError, match="malformed structured output"):
        service.complete_structured("do work", AgentRunOutput)


def test_provider_runtime_repair_fails_raises_with_repair_message(monkeypatch, tmp_path) -> None:
    """When repair also produces bad JSON, raise with a 'repair also failed' message."""
    cfg = _make_cfg(repair_enabled=True)
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    events_path = tmp_path / "events.jsonl"
    events_path.write_text("")

    def fake_run_provider(self, provider, *, model, prompt):
        return ProviderRunResult(
            provider="copilot",
            model=model,
            output="still not json",
            diagnostics=[],
            session_events_path=str(events_path),
        )

    def fake_run_copilot_repair(self, *, model, prompt):
        return "also not valid json after repair"

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)
    monkeypatch.setattr(ProviderRuntimeService, "_run_copilot_repair", fake_run_copilot_repair)
    monkeypatch.setattr(
        "orchestration.services.provider_runtime.extract_session_repair_context",
        lambda path: "some context",
    )

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    with pytest.raises(RuntimeError, match="repair also failed"):
        service.complete_structured("do work", AgentRunOutput)


def test_provider_runtime_subprocess_failure_has_distinct_message(monkeypatch, tmp_path) -> None:
    """Subprocess RuntimeError is distinct from malformed-output error."""
    cfg = _make_cfg()
    monkeypatch.setattr("orchestration.services.provider_runtime.get_config", lambda: cfg)

    def fake_run_provider(self, provider, *, model, prompt):
        raise RuntimeError("exit code 1")

    monkeypatch.setattr(ProviderRuntimeService, "_run_provider", fake_run_provider)

    service = ProviderRuntimeService(stage="agent_run", repo_root=str(tmp_path))
    with pytest.raises(RuntimeError, match="subprocess failed"):
        service.complete_structured("do work", AgentRunOutput)


def test_deterministic_gates_success_sets_waiting_for_human(tmp_path, monkeypatch) -> None:
    """After gates pass cleanly the workflow waits for the human to run task-ship."""
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    _patch_deterministic_deps(monkeypatch, verification=_verification_pass(), policy=V3PolicyResult(blocked=False))

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "waiting_for_human"
    assert pipeline.blockers == []
    assert pipeline.v3_permanent_failure_reason is None


def test_render_next_action_ready_to_ship(tmp_path) -> None:
    """_next_action shows the task-ship hint when gates passed cleanly."""
    from orchestration.render import render_execution_journal
    from orchestration.models.agent_run import AgentRunOutput as ARO

    state = _v3_state(tmp_path)
    state.workflow_status = "waiting_for_human"
    state.current_stage = "deterministic_gates"
    state.agent_run_output = _agent_output()
    state.blockers = []

    rendered = render_execution_journal(state)
    assert "task-ship" in rendered
    assert "make task-ship" in rendered


def test_render_next_action_high_risk_gate(tmp_path) -> None:
    """_next_action shows high-risk approval hint when blockers are present."""
    from orchestration.render import render_execution_journal

    state = _v3_state(tmp_path)
    state.workflow_status = "waiting_for_human"
    state.current_stage = "deterministic_gates"
    state.agent_run_output = _agent_output()
    state.blockers = ["High-risk finding: potential secret exposure."]

    rendered = render_execution_journal(state)
    assert "high-risk" in rendered.lower() or "High-risk" in rendered


# ---- Tests for verification_commands_run no-hard-gate contract ----

def _agent_output_with_no_verification_commands() -> AgentRunOutput:
    """Same as _agent_output() but verification_commands_run is intentionally empty."""
    out = _agent_output()
    out.verification_commands_run = []
    return out


def test_agent_run_does_not_block_when_verification_commands_missing(tmp_path, monkeypatch) -> None:
    """agent_run must NOT block just because model omitted verification_commands_run entries.

    The model reported web/src/App.tsx as changed and git agrees.
    verification_commands_run is intentionally empty — that used to block; now it must not.
    deterministic_gates is the authority for pass/fail; agent_run is only the authority for
    changed_files integrity and semantic_intent/unresolved_failures consistency.
    """
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )

    def fake_complete_structured(self, prompt, model_cls):
        return _agent_output_with_no_verification_commands(), ProviderRunResult(
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

    assert pipeline.workflow_status == "running", (
        "agent_run must not block on missing verification_commands_run entries"
    )
    assert pipeline.agent_run_output is not None
    assert pipeline.blockers == []


def test_agent_run_does_not_block_when_only_some_commands_reported(tmp_path, monkeypatch) -> None:
    """Partial verification_commands_run for the default full suite must not block."""
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )

    partial_output = _agent_output()
    # Only report one command out of the full default suite
    partial_output.verification_commands_run = [
        CommandExecutionCheck(command="make lint", status="pass", evidence="ok"),
    ]

    def fake_complete_structured(self, prompt, model_cls):
        return partial_output, ProviderRunResult(
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

    assert pipeline.workflow_status == "running", (
        "agent_run must not block on partial verification_commands_run"
    )
    assert pipeline.blockers == []


def test_agent_run_still_blocks_on_changed_files_mismatch_regardless_of_verification(tmp_path, monkeypatch) -> None:
    """changed_files integrity is a hard gate independent of verification_commands_run."""
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    # Git says api/ changed; model says web/ changed — mismatch must still block
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["api/app/main.py"],
    )

    output = _agent_output()  # reports web/src/App.tsx, not api/app/main.py
    output.verification_commands_run = [
        CommandExecutionCheck(command="make api-rebuild", status="pass", evidence="ok"),
        CommandExecutionCheck(command="make contract-backend", status="pass", evidence="ok"),
        CommandExecutionCheck(command="make test-backend", status="pass", evidence="ok"),
        CommandExecutionCheck(command="make api-smoke", status="pass", evidence="ok"),
    ]

    def fake_complete_structured(self, prompt, model_cls):
        return output, ProviderRunResult(
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

    assert pipeline.workflow_status == "blocked"
    assert any("changed_files" in b for b in pipeline.blockers)


def test_agent_run_still_blocks_on_intent_vs_unresolved_failures_contradiction(tmp_path, monkeypatch) -> None:
    """semantic_intent_achieved=True with non-empty unresolved_failures is still a hard block."""
    state = _v3_state(tmp_path)

    monkeypatch.setattr(agent_run_node, "render_task_file", lambda pipeline: None)
    monkeypatch.setattr(
        "orchestration.nodes.agent_run.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )

    output = _agent_output()
    output.semantic_intent_achieved = True
    output.unresolved_failures = ["test-frontend failed: one assertion error"]
    output.verification_commands_run = []  # empty — must not block

    def fake_complete_structured(self, prompt, model_cls):
        return output, ProviderRunResult(
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

    assert pipeline.workflow_status == "blocked"
    assert any("unresolved failures" in b for b in pipeline.blockers)


def test_deterministic_gates_is_authoritative_even_when_model_reported_all_pass(tmp_path, monkeypatch) -> None:
    """deterministic_gates blocks on real failure regardless of what model reported."""
    state = _v3_state(tmp_path)
    # Model says everything passed, verification_commands_run is complete
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    # Real deterministic run returns a failure
    _patch_deterministic_deps(
        monkeypatch,
        verification=_verification_fail(),
        policy=V3PolicyResult(blocked=False),
    )

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert any("Deterministic gates failed" in b for b in pipeline.blockers)


def test_deterministic_gates_runs_default_full_suite(tmp_path, monkeypatch) -> None:
    state = _v3_state(tmp_path)
    state.agent_run_output = _agent_output()

    monkeypatch.setattr(
        deterministic_gates_node,
        "get_config",
        lambda: SimpleNamespace(
            max_retries=3,
            v3_require_pre_ship_human_on_high_risk=False,
        ),
    )
    monkeypatch.setattr(deterministic_gates_node, "render_task_file", lambda pipeline: None)
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
        lambda self, changed_files, allowed_paths, extra_changed_files: V3PolicyResult(blocked=False),
    )

    calls: list[tuple[int, object]] = []

    def fake_run_default_suite(self, max_attempts=3, on_code_retry_fix=None):
        calls.append((max_attempts, on_code_retry_fix))
        return _verification_pass(), []

    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.VerificationService.run_default_suite",
        fake_run_default_suite,
    )

    result = deterministic_gates_node.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "waiting_for_human"
    assert calls == [(3, None)]

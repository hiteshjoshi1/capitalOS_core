from __future__ import annotations

from types import SimpleNamespace

from orchestration.models.build import BuildOutput, RetryEntry
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.review import HumanDecision
from orchestration.nodes.build import run


def make_pipeline_state(tmp_path):
    return PipelineState(
        issue=IssueMetadata(
            issue_id="118",
            slug="risk-and-test-pipeline",
            title="Issue 118",
            task_file="tasks/issue-118-risk-and-test-pipeline.md",
            repo_root=str(tmp_path),
            branch="feature/issue-118-risk-and-test-pipeline",
        ),
        plan_output=PlanOutput(
            summary="Planned build",
            architecture_decisions=[],
            risks=[],
            open_questions=[],
            acceptance_criteria=[],
            planned_paths=[
                "api/app/routers/dashboard.py",
                "web/src/components/dashboard/RiskCard.tsx",
            ],
            checklist=[],
        ),
        human_gate_decisions={
            "plan_approval": HumanDecision(
                gate_type="plan_approval",
                decision="approved",
                reviewer="Hitesh",
                notes="Approved",
                questions=[],
                response_requirements=[],
                unresolved_comments=[],
            )
        },
        execution_mode="step",
    )


def patch_build_dependencies(monkeypatch, *, build_output: BuildOutput, changed_files: list[str]):
    monkeypatch.setattr(
        "orchestration.nodes.build.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_retries=3, allowed_aux_files=[]),
    )

    class FakeLLMService:
        def __init__(self, stage, repo_root=None):
            self.stage = stage
            self.repo_root = repo_root

        def complete_structured(self, prompt, model_cls):
            return build_output.model_copy(deep=True)

    monkeypatch.setattr("orchestration.nodes.build.LLMService", FakeLLMService)

    def fake_run_default_suite(self, max_attempts=3, on_code_retry_fix=None):
        from orchestration.models.verification import VerificationCommandResult, VerificationEvidence

        return (
            VerificationEvidence(
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
            ),
            [],
        )

    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        fake_run_default_suite,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: changed_files,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        lambda self, allowed_paths: (changed_files, []),
    )
    monkeypatch.setattr("orchestration.nodes.build.render_task_file", lambda pipeline: None)


def test_build_rerun_clears_stale_build_blockers_and_retries(tmp_path, monkeypatch):
    state = make_pipeline_state(tmp_path)
    stale_retry = RetryEntry(
        label="api-smoke",
        attempt=1,
        max_attempts=3,
        command="make api-smoke",
        exit_code=2,
        classification="code",
        failure_log_path=".task-flow/failures/stale.log",
    )
    state.build_output = BuildOutput(
        summary="Old failed build",
        changed_files=["orchestration/cli.py"],
        retry_entries=[stale_retry],
    )
    state.retry_log = [stale_retry]
    state.blockers = [
        "Verification suite failed during build.",
        "Build validation failed: old invalid output.",
        "Out-of-scope changed files detected during build: orchestration/cli.py",
        "A blocker from another stage",
    ]

    patch_build_dependencies(
        monkeypatch,
        build_output=BuildOutput(
            summary="Implemented planned changes",
            changed_files=[],
            completed_checklist_item_ids=[],
            implementation_notes=[],
        ),
        changed_files=["api/app/routers/dashboard.py"],
    )

    result = run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "running"
    assert pipeline.retry_log == []
    assert pipeline.build_output is not None
    assert pipeline.build_output.retry_entries == []
    assert pipeline.blockers == ["A blocker from another stage"]


def test_build_blocks_when_planned_paths_are_unchanged(tmp_path, monkeypatch):
    state = make_pipeline_state(tmp_path)

    patch_build_dependencies(
        monkeypatch,
        build_output=BuildOutput(
            summary="Implemented something else",
            changed_files=[],
            completed_checklist_item_ids=[],
            implementation_notes=[],
        ),
        changed_files=["orchestration/cli.py"],
    )

    result = run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert "Build validation failed: no files under the planned paths were changed." in pipeline.blockers


def test_build_blocks_bogus_write_permission_claim(tmp_path, monkeypatch):
    state = make_pipeline_state(tmp_path)

    patch_build_dependencies(
        monkeypatch,
        build_output=BuildOutput(
            summary="Unable to implement changes due to filesystem write permission restrictions.",
            changed_files=[],
            completed_checklist_item_ids=[],
            implementation_notes=[],
        ),
        changed_files=["api/app/routers/dashboard.py"],
    )

    result = run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert (
        "Build validation failed: model reported filesystem write permission restrictions, "
        "but the repo root is writable."
    ) in pipeline.blockers


def test_build_blocks_gracefully_when_builder_fails_before_structured_output(tmp_path, monkeypatch):
    state = make_pipeline_state(tmp_path)

    monkeypatch.setattr(
        "orchestration.nodes.build.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_retries=3, allowed_aux_files=[]),
    )

    class FakeLLMService:
        def __init__(self, stage, repo_root=None):
            self.stage = stage
            self.repo_root = repo_root

        def complete_structured(self, prompt, model_cls):
            raise RuntimeError("Copilot subprocess failed during `build`.")

    monkeypatch.setattr("orchestration.nodes.build.LLMService", FakeLLMService)
    monkeypatch.setattr("orchestration.nodes.build.render_task_file", lambda pipeline: None)

    result = run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert "Builder failed before structured output was recorded." in pipeline.blockers
    assert any("Copilot subprocess failed during `build`." in error for error in pipeline.errors)


def test_build_persists_blocked_state_when_exception_escapes_after_builder_changes(tmp_path, monkeypatch):
    state = make_pipeline_state(tmp_path)

    monkeypatch.setattr(
        "orchestration.nodes.build.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_retries=3, allowed_aux_files=[]),
    )

    class FakeLLMService:
        def __init__(self, stage, repo_root=None):
            self.stage = stage
            self.repo_root = repo_root

        def complete_structured(self, prompt, model_cls):
            return model_cls(
                summary="Implemented feature",
                changed_files=[],
                completed_checklist_item_ids=["CHK-1"],
                implementation_notes=["done"],
            )

    monkeypatch.setattr("orchestration.nodes.build.LLMService", FakeLLMService)
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=3, on_code_retry_fix=None: (_ for _ in ()).throw(RuntimeError("make e2e failed")),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx", "web/tests/e2e/home.spec.ts"],
    )
    monkeypatch.setattr("orchestration.nodes.build.render_task_file", lambda pipeline: None)

    result = run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "blocked"
    assert "Build stage crashed after repository changes may have been applied." in pipeline.blockers
    assert any("make e2e failed" in error for error in pipeline.errors)
    assert pipeline.build_output is not None
    assert "web/src/App.tsx" in pipeline.build_output.changed_files

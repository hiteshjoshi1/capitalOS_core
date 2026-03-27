from __future__ import annotations

from types import SimpleNamespace

from orchestration.models.build import BuildOutput, RetryEntry
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.review import AgentReview, HumanReview, ReviewCycle
from orchestration.models.rework import ReworkAnalysis, ReworkCycle, ReworkImplementationResult
from orchestration.models.verification import VerificationCommandResult, VerificationEvidence
from orchestration.nodes import agent_review, escalation_review, human_review, rework_analysis, rework_implementation


def _base_pipeline(tmp_path) -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="123",
            slug="test",
            title="Test",
            task_file="tasks/issue-123-test.md",
            repo_root=str(tmp_path),
            branch="feature/issue-123-test",
        ),
        plan_output=PlanOutput(
            summary="Planned workflow",
            architecture_decisions=[],
            risks=[],
            open_questions=[],
            acceptance_criteria=[],
            planned_paths=["web/src/App.tsx", "orchestration/"],
            checklist=[],
        ),
        execution_mode="step",
    )


def _failed_verification() -> VerificationEvidence:
    return VerificationEvidence(
        results=[
            VerificationCommandResult(
                name="contract-frontend",
                command="make contract-frontend",
                status="fail",
                exit_code=2,
                output_excerpt="contract failed",
            )
        ],
        any_failures=True,
    )


def _passed_verification() -> VerificationEvidence:
    return VerificationEvidence(
        results=[
            VerificationCommandResult(
                name="contract-frontend",
                command="make contract-frontend",
                status="pass",
                exit_code=0,
                output_excerpt="ok",
            )
        ],
        any_failures=False,
    )


def test_agent_review_skips_model_when_verification_is_red(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.build_output = BuildOutput(
        summary="Implemented feature",
        changed_files=["web/src/App.tsx"],
        verification=_failed_verification(),
    )

    monkeypatch.setattr(
        "orchestration.nodes.agent_review.get_config",
        lambda: SimpleNamespace(reviewer_model="reviewer-model"),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=1, on_code_retry_fix=None: (_passed_verification(), []),
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.LLMService.complete_structured",
        lambda self, prompt, model_cls: (_ for _ in ()).throw(AssertionError("reviewer should not be called")),
    )

    result = agent_review.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_review_cycle()

    assert cycle is not None
    assert cycle.agent_review is not None
    assert cycle.agent_review.model_name == "deterministic-gate"
    assert cycle.status == "needs_fixes"


def test_escalation_review_skips_model_when_verification_is_red(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.build_output = BuildOutput(
        summary="Implemented feature",
        changed_files=["web/src/App.tsx"],
        verification=_failed_verification(),
    )
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="escalate",
                risk="high",
                summary="Need escalation",
            ),
            status="in_review",
        )
    )
    state.active_review_cycle_id = "R1"

    monkeypatch.setattr(
        "orchestration.nodes.escalation_review.get_config",
        lambda: SimpleNamespace(review_escalation_model="escalation-model"),
    )
    monkeypatch.setattr(
        "orchestration.nodes.escalation_review.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.escalation_review.LLMService.complete_structured",
        lambda self, prompt, model_cls: (_ for _ in ()).throw(AssertionError("escalation model should not be called")),
    )

    result = escalation_review.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_review_cycle()

    assert cycle is not None
    assert cycle.escalation_review is not None
    assert cycle.escalation_review.model_name == "deterministic-gate"
    assert cycle.status == "needs_fixes"


def test_rework_analysis_reuses_existing_analysis_on_reentry(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="needs_fixes",
                risk="medium",
                summary="Needs work",
                findings=["Fix routing"],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"

    monkeypatch.setattr(
        "orchestration.nodes.rework_analysis.IntegrityService.assert_matches_planned_hash",
        lambda self, pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_analysis.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_rework_cycles=2),
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_analysis.render_task_file",
        lambda pipeline: None,
    )

    calls = {"count": 0}

    def fake_complete_structured(self, prompt, model_cls):
        calls["count"] += 1
        return model_cls(
            rework_cycle_id="W1",
            review_id="R1",
            root_cause="Routing issue",
            findings_addressed=["Fix routing"],
            planned_changes=["Update routing"],
            validation_plan=["Run verification"],
            unresolved_assumptions=[],
            answer_matrix=[],
        )

    monkeypatch.setattr(
        "orchestration.nodes.rework_analysis.LLMService.complete_structured",
        fake_complete_structured,
    )

    first = rework_analysis.run({"pipeline": state.model_dump(mode="json")})
    second = rework_analysis.run(first)
    pipeline = PipelineState.model_validate(second["pipeline"])

    assert calls["count"] == 1
    assert pipeline.get_active_rework_cycle() is not None


def test_agent_review_skips_model_when_required_checks_are_unresolved(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="needs_fixes",
                risk="medium",
                summary="Needs work",
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Fix the UI contract regressions.",
                required_checks=["ui.dashboard.exposure_labels"],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            implementation=ReworkImplementationResult(
                rework_cycle_id="W1",
                review_id="R1",
                summary="Applied partial fixes",
                changed_files=["web/src/App.tsx"],
                verification_summary="green",
                verification=_passed_verification(),
                resolved_required_checks=[],
            ),
            status="implementation_complete",
        )
    )
    state.active_rework_cycle_id = "W1"

    monkeypatch.setattr(
        "orchestration.nodes.agent_review.get_config",
        lambda: SimpleNamespace(reviewer_model="reviewer-model"),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=1, on_code_retry_fix=None: (_passed_verification(), []),
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.LLMService.complete_structured",
        lambda self, prompt, model_cls: (_ for _ in ()).throw(AssertionError("reviewer should not be called")),
    )

    result = agent_review.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_review_cycle()

    assert cycle is not None
    assert cycle.agent_review is not None
    assert cycle.agent_review.model_name == "deterministic-gate"
    assert "ui.dashboard.exposure_labels" in cycle.agent_review.findings[0]


def test_agent_review_calls_model_once_required_checks_are_resolved(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="needs_fixes",
                risk="medium",
                summary="Needs work",
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Fix the UI contract regressions.",
                required_checks=["ui.dashboard.exposure_labels"],
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            implementation=ReworkImplementationResult(
                rework_cycle_id="W1",
                review_id="R1",
                summary="Applied full fixes",
                changed_files=["web/src/App.tsx"],
                verification_summary="green",
                verification=_passed_verification(),
                resolved_required_checks=["ui.dashboard.exposure_labels"],
            ),
            status="implementation_complete",
        )
    )
    state.active_rework_cycle_id = "W1"

    monkeypatch.setattr(
        "orchestration.nodes.agent_review.get_config",
        lambda: SimpleNamespace(reviewer_model="reviewer-model"),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=1, on_code_retry_fix=None: (_passed_verification(), []),
    )
    monkeypatch.setattr(
        "orchestration.nodes.agent_review.LLMService.complete_structured",
        lambda self, prompt, model_cls: model_cls(
            review_id="R2",
            model_name="reviewer-model",
            decision="approved",
            risk="low",
            summary="Looks good",
            findings=[],
            test_gaps=[],
            verification_considered=True,
        ),
    )

    result = agent_review.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_review_cycle()

    assert cycle is not None
    assert cycle.agent_review is not None
    assert cycle.agent_review.model_name == "reviewer-model"


def test_rework_implementation_autofix_callback_accepts_prior_attempts(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="needs_fixes",
                risk="medium",
                summary="Needs work",
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Fix the failing checks.",
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            analysis=ReworkAnalysis(
                rework_cycle_id="W1",
                review_id="R1",
                root_cause="Verification mismatch",
                planned_changes=["Adjust the failing checks"],
                validation_plan=["Run verification"],
            ),
            status="analysis_complete",
        )
    )
    state.active_rework_cycle_id = "W1"

    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_retries=3, allowed_aux_files=[]),
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.IntegrityService.assert_matches_planned_hash",
        lambda self, pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx"],
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        lambda self, allowed_paths: (["web/src/App.tsx"], []),
    )

    class FakeLLMService:
        def __init__(self, stage, repo_root=None):
            self.stage = stage
            self.repo_root = repo_root

        def complete_structured(self, prompt, model_cls):
            return model_cls(
                rework_cycle_id="W1",
                review_id="R1",
                summary="Applied a rework fix.",
                changed_files=["web/src/App.tsx"],
                resolved_required_checks=["Adjusted failing checks"],
            )

    monkeypatch.setattr("orchestration.nodes.rework_implementation.LLMService", FakeLLMService)

    fix_calls = []

    def fake_invoke_fix(
        self,
        *,
        label,
        command,
        exit_code,
        output,
        prior_attempts,
        allowed_paths=None,
        primary_objective=None,
    ):
        fix_calls.append(
            {
                "label": label,
                "command": command,
                "exit_code": exit_code,
                "output": output,
                "prior_attempts": prior_attempts,
                "allowed_paths": allowed_paths,
                "primary_objective": primary_objective,
            }
        )

    monkeypatch.setattr(
        "orchestration.services.builder_fix.BuilderFixService.invoke_fix",
        fake_invoke_fix,
    )

    def fake_run_default_suite(self, max_attempts=3, on_code_retry_fix=None):
        assert on_code_retry_fix is not None
        prior_attempts = [
            RetryEntry(
                label="test-frontend",
                attempt=1,
                max_attempts=3,
                command="make test-frontend",
                exit_code=2,
                classification="code",
                notes="Failure reason: element not found",
            )
        ]
        on_code_retry_fix(
            "test-frontend",
            "make test-frontend",
            2,
            "TestingLibraryElementError",
            prior_attempts,
        )
        return (
            VerificationEvidence(
                results=[
                    VerificationCommandResult(
                        name="test-frontend",
                        command="make test-frontend",
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

    result = rework_implementation.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])

    assert pipeline.workflow_status == "running"
    assert fix_calls
    assert fix_calls[0]["label"] == "test-frontend"
    assert len(fix_calls[0]["prior_attempts"]) == 1
    assert "Fix the failing checks." in fix_calls[0]["primary_objective"]
    assert "web/src/App.tsx" in fix_calls[0]["allowed_paths"]
    assert "web/src/__tests__/" not in fix_calls[0]["allowed_paths"]
    assert "api/tests/" not in fix_calls[0]["allowed_paths"]


def test_rework_implementation_blocks_post_verification_out_of_scope_files(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R1",
            source="build",
            agent_review=AgentReview(
                review_id="R1",
                model_name="reviewer-model",
                decision="needs_fixes",
                risk="medium",
                summary="Needs work",
                findings=["Move dashboard detail cards to Wealth Overview"],
            ),
            human_review=HumanReview(
                review_id="R1",
                decision="needs_fixes",
                reviewer="Hitesh",
                notes="Implement the dashboard and wealth split, not test-only changes.",
            ),
            status="needs_fixes",
        )
    )
    state.active_review_cycle_id = "R1"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            analysis=ReworkAnalysis(
                rework_cycle_id="W1",
                review_id="R1",
                root_cause="Dashboard split not implemented",
                planned_changes=["Update web/src/App.tsx"],
                validation_plan=["Run verification"],
            ),
            status="analysis_complete",
        )
    )
    state.active_rework_cycle_id = "W1"

    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.get_config",
        lambda: SimpleNamespace(builder_model="builder-model", max_retries=3, allowed_aux_files=[]),
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.IntegrityService.assert_matches_planned_hash",
        lambda self, pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.rework_implementation.render_task_file",
        lambda pipeline: None,
    )

    changed_calls = iter(
        [
            ["web/src/App.tsx"],
            ["web/src/App.tsx", "web/src/__tests__/App.test.tsx"],
        ]
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: next(changed_calls),
    )

    captured_allowed = {}

    def fake_stage_scoped_changes(self, allowed_paths):
        final_changes = ["web/src/App.tsx", "web/src/__tests__/App.test.tsx"]
        captured_allowed["paths"] = list(allowed_paths)
        blocked = [
            path
            for path in final_changes
            if not rework_implementation.ScopePolicyService.is_path_allowed(path, allowed_paths)
        ]
        staged = [path for path in final_changes if path not in blocked]
        return staged, blocked

    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        fake_stage_scoped_changes,
    )

    class FakeLLMService:
        def __init__(self, stage, repo_root=None):
            self.stage = stage
            self.repo_root = repo_root

        def complete_structured(self, prompt, model_cls):
            return model_cls(
                rework_cycle_id="W1",
                review_id="R1",
                summary="Applied the dashboard rework.",
                changed_files=["web/src/App.tsx"],
                resolved_required_checks=["Update dashboard implementation"],
            )

    monkeypatch.setattr("orchestration.nodes.rework_implementation.LLMService", FakeLLMService)
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=3, on_code_retry_fix=None: (_passed_verification(), []),
    )

    result = rework_implementation.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_rework_cycle()

    assert pipeline.workflow_status == "blocked"
    assert cycle is not None
    assert cycle.implementation is not None
    assert cycle.implementation.changed_files == [
        "web/src/App.tsx",
        "web/src/__tests__/App.test.tsx",
    ]
    assert "web/src/__tests__/" not in captured_allowed["paths"]
    assert pipeline.blockers[-1].endswith("web/src/__tests__/App.test.tsx")
    review_cycle = pipeline.get_active_review_cycle()
    assert review_cycle is not None
    assert review_cycle.status == "scope_gate_pending"
    assert review_cycle.source == "rework"
    assert review_cycle.source_rework_cycle_id == "W1"
    assert review_cycle.extra_changed_files[0].path == "web/src/__tests__/App.test.tsx"


def test_human_review_handles_extra_files_approval_gate(tmp_path, monkeypatch):
    state = _base_pipeline(tmp_path)
    state.review_cycles.append(
        ReviewCycle(
            review_id="R2",
            source="rework",
            source_rework_cycle_id="W1",
            extra_changed_files=[
                {
                    "path": "web/src/__tests__/App.test.tsx",
                    "reason": "Likely test update required to align verification with the implementation change.",
                    "reason_source": "inferred",
                }
            ],
            status="scope_gate_pending",
        )
    )
    state.active_review_cycle_id = "R2"
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            status="blocked",
        )
    )
    state.active_rework_cycle_id = "W1"

    interrupts = []

    monkeypatch.setattr(
        "orchestration.nodes.human_review.render_task_file",
        lambda pipeline: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.human_review.emit_stage_start",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.human_review.emit_waiting_for_human",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "orchestration.nodes.human_review.emit_stage_end",
        lambda *args, **kwargs: None,
    )

    def fake_interrupt(payload):
        interrupts.append(payload)
        return {
            "gate_type": "extra_files_approval",
            "decision": "approved",
            "reviewer": "Hitesh",
            "notes": "Okay to keep the extra file.",
            "questions": [],
            "required_checks": [],
            "response_requirements": [],
            "unresolved_comments": [],
            "approved_retry_count": 0,
        }

    monkeypatch.setattr("orchestration.nodes.human_review.interrupt", fake_interrupt)

    result = human_review.run({"pipeline": state.model_dump(mode="json")})
    pipeline = PipelineState.model_validate(result["pipeline"])
    cycle = pipeline.get_active_review_cycle()

    assert interrupts[0]["gate"] == "extra_files_approval"
    assert cycle is not None
    assert cycle.status == "scope_approved"
    assert cycle.extra_files_review is not None
    assert cycle.extra_files_review.gate_type == "extra_files_approval"
    assert pipeline.workflow_status == "running"
    assert "web/src/__tests__/App.test.tsx" in pipeline.approved_extra_file_paths()

from __future__ import annotations

from orchestration.models.build import RetryEntry
from orchestration.models.verification import VerificationCommandResult
from orchestration.services.verification import VerificationService


def test_infra_failures_retry_once_without_autofix(tmp_path, monkeypatch):
    service = VerificationService(str(tmp_path))
    outputs = [
        (2, "Cannot connect to the Docker daemon at unix:///tmp/docker.sock"),
        (2, "Cannot connect to the Docker daemon at unix:///tmp/docker.sock"),
    ]
    fix_calls = []

    monkeypatch.setattr(service, "_run_raw", lambda name, command: outputs.pop(0))

    result, retries = service.run_with_retry_policy(
        name="api-rebuild",
        command="make api-rebuild",
        max_attempts=3,
        on_code_retry_fix=lambda *args: fix_calls.append(args),
    )

    assert result.status == "fail"
    assert len(retries) == 2
    assert all(entry.classification == "infra" for entry in retries)
    assert fix_calls == []


def test_code_failures_invoke_fix_before_each_new_attempt(tmp_path, monkeypatch):
    service = VerificationService(str(tmp_path))
    outputs = [
        (2, "AssertionError: expected value"),
        (2, "AssertionError: updated value still wrong"),
        (0, "all good"),
    ]
    fix_calls = []

    monkeypatch.setattr(service, "_run_raw", lambda name, command: outputs.pop(0))

    def fake_fix(*args):
        fix_calls.append(args)

    result, retries = service.run_with_retry_policy(
        name="test-frontend",
        command="make test-frontend",
        max_attempts=3,
        on_code_retry_fix=fake_fix,
    )

    assert result.status == "pass"
    assert len(retries) == 2
    assert len(fix_calls) == 2
    assert retries[0].notes.startswith("Code failure analyzed and auto-fix applied:")
    assert retries[1].notes.startswith("Code failure analyzed and auto-fix applied:")


def test_code_failures_stop_immediately_when_no_fix_callback_exists(tmp_path, monkeypatch):
    service = VerificationService(str(tmp_path))
    monkeypatch.setattr(service, "_run_raw", lambda name, command: (2, "AssertionError: expected value"))

    result, retries = service.run_with_retry_policy(
        name="test-frontend",
        command="make test-frontend",
        max_attempts=3,
        on_code_retry_fix=None,
    )

    assert result.status == "fail"
    assert len(retries) == 1
    assert retries[0].notes.startswith("Code failure with no auto-fix available:")


def test_default_suite_restarts_after_green_run_with_late_code_fix(tmp_path, monkeypatch):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "playwright.config.ts").write_text("export default {};\n")

    service = VerificationService(str(tmp_path))
    calls: list[str] = []
    e2e_runs = {"count": 0}

    def fake_run_with_retry_policy(*, name, command, max_attempts, on_code_retry_fix=None):
        calls.append(name)
        if name == "e2e":
            e2e_runs["count"] += 1
            if e2e_runs["count"] == 1:
                return (
                    VerificationCommandResult(
                        name=name,
                        command=command,
                        status="pass",
                        exit_code=0,
                        output_excerpt="fixed and green",
                    ),
                    [
                        RetryEntry(
                            label=name,
                            attempt=1,
                            max_attempts=3,
                            command=command,
                            exit_code=2,
                            classification="code",
                            notes="Code failure analyzed and auto-fix applied: fixed e2e",
                        )
                    ],
                )

        return (
            VerificationCommandResult(
                name=name,
                command=command,
                status="pass",
                exit_code=0,
                output_excerpt="ok",
            ),
            [],
        )

    monkeypatch.setattr(service, "run_with_retry_policy", fake_run_with_retry_policy)

    evidence, retries = service.run_default_suite(max_attempts=3)

    assert evidence.any_failures is False
    assert retries
    assert calls.count("lint") == 2
    assert calls.count("contract-backend") == 1
    assert calls.count("test-backend") == 1
    assert calls.count("contract-frontend") == 2
    assert calls.count("test-frontend") == 2
    assert calls.count("e2e") == 2


def test_default_suite_restarts_from_backend_family_after_backend_fix(tmp_path, monkeypatch):
    service = VerificationService(str(tmp_path))
    calls: list[str] = []
    backend_runs = {"count": 0}

    def fake_run_with_retry_policy(*, name, command, max_attempts, on_code_retry_fix=None):
        calls.append(name)
        if name == "contract-backend":
            backend_runs["count"] += 1
            if backend_runs["count"] == 1:
                return (
                    VerificationCommandResult(
                        name=name,
                        command=command,
                        status="pass",
                        exit_code=0,
                        output_excerpt="fixed and green",
                    ),
                    [
                        RetryEntry(
                            label=name,
                            attempt=1,
                            max_attempts=3,
                            command=command,
                            exit_code=2,
                            classification="code",
                            notes="Code failure analyzed and auto-fix applied: fixed backend contract",
                        )
                    ],
                )

        return (
            VerificationCommandResult(
                name=name,
                command=command,
                status="pass",
                exit_code=0,
                output_excerpt="ok",
            ),
            [],
        )

    monkeypatch.setattr(service, "run_with_retry_policy", fake_run_with_retry_policy)

    evidence, retries = service.run_default_suite(max_attempts=3)

    assert evidence.any_failures is False
    assert retries
    assert calls.count("lint") == 2
    assert calls.count("typecheck") == 2
    assert calls.count("api-rebuild") == 2
    assert calls.count("contract-backend") == 2
    assert calls.count("test-backend") == 2
    assert calls.count("contract-frontend") == 2


def test_expected_commands_for_backend_only_changes(tmp_path):
    service = VerificationService(str(tmp_path))
    commands = service.expected_commands_for_changed_files(str(tmp_path), ["api/app/main.py", "migrations/001_init.sql"])
    assert commands == [
        "make api-rebuild",
        "make contract-backend",
        "make test-backend",
        "make api-smoke",
    ]


def test_expected_commands_for_pipeline_only_changes(tmp_path):
    service = VerificationService(str(tmp_path))
    commands = service.expected_commands_for_changed_files(
        str(tmp_path),
        ["orchestration/nodes/agent_run.py", "docs/workflows/ai-task-flow.md", "Makefile"],
    )
    assert commands == ["make orch-test"]

from __future__ import annotations

from orchestration.services.verification import VerificationService


def test_infra_failures_retry_once_without_autofix(tmp_path, monkeypatch):
    service = VerificationService(str(tmp_path))
    outputs = [
        (2, "Cannot connect to the Docker daemon at unix:///tmp/docker.sock"),
        (2, "Cannot connect to the Docker daemon at unix:///tmp/docker.sock"),
    ]
    fix_calls = []

    monkeypatch.setattr(service, "_run_raw", lambda command: outputs.pop(0))

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

    monkeypatch.setattr(service, "_run_raw", lambda command: outputs.pop(0))

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
    monkeypatch.setattr(service, "_run_raw", lambda command: (2, "AssertionError: expected value"))

    result, retries = service.run_with_retry_policy(
        name="test-frontend",
        command="make test-frontend",
        max_attempts=3,
        on_code_retry_fix=None,
    )

    assert result.status == "fail"
    assert len(retries) == 1
    assert retries[0].notes.startswith("Code failure with no auto-fix available:")

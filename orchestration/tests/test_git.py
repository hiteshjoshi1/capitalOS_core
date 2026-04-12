from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from orchestration.services.git import GitService


def test_run_returns_stdout_when_command_succeeds(monkeypatch):
    def fake_run(args, cwd, capture_output, text):
        assert args == ["git", "status"]
        assert cwd == "/tmp/repo"
        return SimpleNamespace(returncode=0, stdout="clean\n", stderr="")

    monkeypatch.setattr("orchestration.services.git.subprocess.run", fake_run)

    service = GitService("/tmp/repo")
    assert service.run("status") == "clean"


def test_run_preserves_leading_status_space_for_porcelain_output(monkeypatch):
    def fake_run(args, cwd, capture_output, text):
        assert args == ["git", "status", "--porcelain"]
        assert cwd == "/tmp/repo"
        return SimpleNamespace(returncode=0, stdout=" M tasks/issue.md\n", stderr="")

    monkeypatch.setattr("orchestration.services.git.subprocess.run", fake_run)

    service = GitService("/tmp/repo")
    assert service.run("status", "--porcelain") == " M tasks/issue.md"


def test_run_raises_when_checking_failed_command(monkeypatch):
    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda args, cwd, capture_output, text: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="fatal: bad revision",
        ),
    )

    service = GitService("/tmp/repo")
    with pytest.raises(RuntimeError, match="fatal: bad revision"):
        service.run("rev-parse", "HEAD")


def test_run_allows_failed_command_when_check_false(monkeypatch):
    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda args, cwd, capture_output, text: SimpleNamespace(
            returncode=1,
            stdout="detached\n",
            stderr="warning",
        ),
    )

    service = GitService("/tmp/repo")
    assert service.run("symbolic-ref", "HEAD", check=False) == "detached"


def test_current_branch_delegates_to_run(monkeypatch):
    monkeypatch.setattr(
        GitService,
        "run",
        lambda self, *args, **kwargs: "feature/test",
    )

    assert GitService("/tmp/repo").current_branch() == "feature/test"


def test_checkout_prepare_branch_checks_out_existing_branch(monkeypatch):
    calls = []

    def fake_service_run(self, *args, **kwargs):
        calls.append(args)
        return ""

    def fake_run(args, cwd):
        assert args[-1] == "refs/heads/feature/test"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(GitService, "run", fake_service_run)
    monkeypatch.setattr("orchestration.services.git.subprocess.run", fake_run)

    GitService("/tmp/repo").checkout_main_and_prepare_branch("feature/test")

    assert calls == [
        ("checkout", "main"),
        ("pull", "--rebase"),
        ("checkout", "feature/test"),
    ]


def test_checkout_prepare_branch_creates_new_branch_when_missing(monkeypatch):
    calls = []

    def fake_service_run(self, *args, **kwargs):
        calls.append(args)
        return ""

    monkeypatch.setattr(GitService, "run", fake_service_run)
    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda args, cwd: SimpleNamespace(returncode=1),
    )

    GitService("/tmp/repo").checkout_main_and_prepare_branch("feature/test", base_branch="develop")

    assert calls == [
        ("checkout", "develop"),
        ("pull", "--rebase"),
        ("checkout", "-b", "feature/test"),
    ]


def test_ensure_clean_worktree_except_allows_only_permitted_paths(monkeypatch):
    monkeypatch.setattr(
        GitService,
        "run",
        lambda self, *args, **kwargs: " M tasks/issue.md\n?? web/src/App.tsx\n",
    )

    service = GitService("/tmp/repo")

    with pytest.raises(RuntimeError, match="web/src/App.tsx"):
        service.ensure_clean_worktree_except(["tasks/issue.md"])


def test_ensure_clean_worktree_except_returns_when_clean(monkeypatch):
    monkeypatch.setattr(GitService, "run", lambda self, *args, **kwargs: "")
    GitService("/tmp/repo").ensure_clean_worktree_except(["tasks/issue.md"])


def test_ensure_clean_worktree_except_allows_dirty_task_file(monkeypatch):
    monkeypatch.setattr(
        GitService,
        "run",
        lambda self, *args, **kwargs: " M tasks/issue-132.md",
    )

    GitService("/tmp/repo").ensure_clean_worktree_except(["tasks/issue-132.md"])


def test_changed_files_merges_unique_paths(monkeypatch):
    output = "web/src/App.tsx\nweb/src/App.tsx\napi/app/main.py\n"

    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output),
    )

    service = GitService("/tmp/repo")
    assert service.changed_files() == ["api/app/main.py", "web/src/App.tsx"]


def test_add_calls_git_add_when_paths_provided(monkeypatch):
    calls = []
    monkeypatch.setattr(GitService, "run", lambda self, *args, **kwargs: calls.append(args) or "")

    GitService("/tmp/repo").add("a.py", "b.py")
    assert calls == [("add", "a.py", "b.py")]


def test_add_skips_when_no_paths_provided(monkeypatch):
    calls = []
    monkeypatch.setattr(GitService, "run", lambda self, *args, **kwargs: calls.append(args) or "")

    GitService("/tmp/repo").add()
    assert calls == []


def test_stage_scoped_changes_stages_allowed_and_blocks_other_paths(monkeypatch):
    monkeypatch.setattr(
        GitService,
        "changed_files",
        lambda self: ["api/app/main.py", "web/src/App.tsx", "README.md"],
    )
    added = []
    monkeypatch.setattr(GitService, "add", lambda self, *paths: added.extend(paths))

    staged, blocked = GitService("/tmp/repo").stage_scoped_changes(["api/", "web/src/App.tsx"])

    assert staged == ["api/app/main.py", "web/src/App.tsx"]
    assert blocked == ["README.md"]
    assert added == ["api/app/main.py", "web/src/App.tsx"]


def test_commit_if_needed_returns_false_when_no_staged_diff(monkeypatch):
    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda args, cwd: SimpleNamespace(returncode=0),
    )

    service = GitService("/tmp/repo")
    assert service.commit_if_needed("msg") is False


def test_commit_if_needed_commits_when_diff_exists(monkeypatch):
    monkeypatch.setattr(
        "orchestration.services.git.subprocess.run",
        lambda args, cwd: SimpleNamespace(returncode=1),
    )
    calls = []
    monkeypatch.setattr(GitService, "run", lambda self, *args, **kwargs: calls.append(args) or "")

    service = GitService("/tmp/repo")
    assert service.commit_if_needed("ship it") is True
    assert calls == [("commit", "-m", "ship it")]


def test_push_uses_upstream_origin(monkeypatch):
    calls = []
    monkeypatch.setattr(GitService, "run", lambda self, *args, **kwargs: calls.append(args) or "")

    GitService("/tmp/repo").push("feature/test")
    assert calls == [("push", "-u", "origin", "feature/test")]


def test_task_file_exists_checks_repo_relative_path(tmp_path):
    task = tmp_path / "tasks" / "issue-1-test.md"
    task.parent.mkdir(parents=True)
    task.write_text("# hi\n")

    service = GitService(str(tmp_path))
    assert service.task_file_exists("tasks/issue-1-test.md") is True
    assert service.task_file_exists("tasks/missing.md") is False

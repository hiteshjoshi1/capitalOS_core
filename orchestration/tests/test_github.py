from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestration.services.github import GitHubService, PullRequestResult


def test_run_executes_gh_in_repo_root(monkeypatch):
    calls = []

    def fake_run(args, cwd, capture_output, text):
        calls.append((args, cwd, capture_output, text))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("orchestration.services.github.subprocess.run", fake_run)

    service = GitHubService("/tmp/repo")
    service._run("auth", "status")

    assert calls == [(["gh", "auth", "status"], "/tmp/repo", True, True)]


def test_pr_exists_returns_true_on_success(monkeypatch):
    monkeypatch.setattr(
        GitHubService,
        "_run",
        lambda self, *args: SimpleNamespace(returncode=0),
    )

    assert GitHubService("/tmp/repo").pr_exists("feature/test") is True


def test_pr_exists_returns_false_on_failure(monkeypatch):
    monkeypatch.setattr(
        GitHubService,
        "_run",
        lambda self, *args: SimpleNamespace(returncode=1),
    )

    assert GitHubService("/tmp/repo").pr_exists("feature/test") is False


def test_create_pr_skips_when_pr_already_exists(monkeypatch):
    monkeypatch.setattr(GitHubService, "pr_exists", lambda self, branch: True)

    result = GitHubService("/tmp/repo").create_pr(
        branch="feature/test",
        base="main",
        title="T",
        body="B",
    )

    assert result == PullRequestResult(
        created=False,
        url=None,
        message="PR already exists for feature/test.",
    )


def test_create_pr_raises_when_gh_fails(monkeypatch):
    monkeypatch.setattr(GitHubService, "pr_exists", lambda self, branch: False)
    monkeypatch.setattr(
        GitHubService,
        "_run",
        lambda self, *args: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        GitHubService("/tmp/repo").create_pr(
            branch="feature/test",
            base="main",
            title="T",
            body="B",
        )


def test_create_pr_returns_url_from_stdout(monkeypatch):
    monkeypatch.setattr(GitHubService, "pr_exists", lambda self, branch: False)
    calls = []

    def fake_run(self, *args):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout="creating...\nhttps://github.com/example/repo/pull/123\n",
            stderr="",
        )

    monkeypatch.setattr(GitHubService, "_run", fake_run)

    result = GitHubService("/tmp/repo").create_pr(
        branch="feature/test",
        base="main",
        title="Title",
        body="Body",
    )

    assert calls == [
        (
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            "feature/test",
            "--title",
            "Title",
            "--body",
            "Body",
        )
    ]
    assert result == PullRequestResult(
        created=True,
        url="https://github.com/example/repo/pull/123",
        message="Created PR for feature/test.",
    )


def test_create_pr_allows_missing_stdout_url(monkeypatch):
    monkeypatch.setattr(GitHubService, "pr_exists", lambda self, branch: False)
    monkeypatch.setattr(
        GitHubService,
        "_run",
        lambda self, *args: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    result = GitHubService("/tmp/repo").create_pr(
        branch="feature/test",
        base="main",
        title="Title",
        body="Body",
    )

    assert result.url is None
    assert result.created is True

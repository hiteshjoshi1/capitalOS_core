from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class PullRequestResult:
    created: bool
    url: Optional[str]
    message: str


class GitHubService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["gh", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )

    def pr_exists(self, branch: str) -> bool:
        proc = self._run("pr", "view", "--head", branch, "--json", "number")
        return proc.returncode == 0

    def create_pr(self, *, branch: str, base: str, title: str, body: str) -> PullRequestResult:
        if self.pr_exists(branch):
            return PullRequestResult(
                created=False,
                url=None,
                message=f"PR already exists for {branch}.",
            )

        proc = self._run(
            "pr",
            "create",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

        url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
        return PullRequestResult(
            created=True,
            url=url,
            message=f"Created PR for {branch}.",
        )
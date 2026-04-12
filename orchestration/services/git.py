from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List


class GitService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.rstrip("\n")

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def checkout_main_and_prepare_branch(self, branch: str, base_branch: str = "main") -> None:
        self.run("checkout", base_branch)
        self.run("pull", "--rebase")
        exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self.repo_root,
        )
        if exists.returncode == 0:
            self.run("checkout", branch)
        else:
            self.run("checkout", "-b", branch)

    def ensure_clean_worktree_except(self, allowed_paths: List[str]) -> None:
        status = self.run("status", "--porcelain", check=True)
        if not status:
            return
        illegal = []
        for line in status.splitlines():
            path = line[3:].strip()
            if path not in allowed_paths:
                illegal.append(path)
        if illegal:
            raise RuntimeError(
                f"Working tree has changes outside allowed paths: {', '.join(illegal)}"
            )

    def changed_files(self) -> list[str]:
        out = subprocess.run(
            [
                "bash",
                "-lc",
                "git diff --name-only && git diff --cached --name-only && git ls-files --others --exclude-standard",
            ],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return sorted({line.strip() for line in out.splitlines() if line.strip()})

    def add(self, *paths: str) -> None:
        if paths:
            self.run("add", *paths)

    def stage_scoped_changes(self, allowed_paths: Iterable[str]) -> tuple[list[str], list[str]]:
        allowed = [p.strip() for p in allowed_paths if p.strip()]
        changed = self.changed_files()
        staged: list[str] = []
        blocked: list[str] = []

        def is_allowed(path: str) -> bool:
            for a in allowed:
                if path == a:
                    return True
                if a.endswith("/") and path.startswith(a):
                    return True
                if path.startswith(f"{a}/"):
                    return True
            return False

        for path in changed:
            if is_allowed(path):
                self.add(path)
                staged.append(path)
            else:
                blocked.append(path)
        return staged, blocked 

    def commit_if_needed(self, message: str) -> bool:
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.repo_root,
        )
        if diff.returncode == 0:
            return False
        self.run("commit", "-m", message)
        return True

    def push(self, branch: str) -> None:
        self.run("push", "-u", "origin", branch)

    def task_file_exists(self, task_file: str) -> bool:
        return Path(self.repo_root, task_file).exists()

from __future__ import annotations

import subprocess
from textwrap import dedent

from orchestration.models.pipeline import PipelineState
from orchestration.services.config import get_config


class BuilderFixService:
    def __init__(self, state: PipelineState) -> None:
        self.state = state
        self.cfg = get_config()

    def invoke_fix(
        self,
        *,
        label: str,
        command: str,
        exit_code: int,
        output: str,
    ) -> None:
        allowed_paths = {self.state.issue.task_file, *self.cfg.allowed_aux_files}
        if self.state.plan_output is not None:
            allowed_paths.update(self.state.plan_output.allowed_paths())
        if self.state.build_output is not None:
            allowed_paths.update(self.state.build_output.changed_files)
        rework = self.state.get_active_rework_cycle()
        if rework and rework.implementation is not None:
            allowed_paths.update(rework.implementation.changed_files)

        prompt = dedent(
            f"""
            Fix the failing verification command in the current branch.

            Task file: {self.state.issue.task_file}
            Failed command: {command}
            Exit code: {exit_code}
            Failure label: {label}

            Failure output:
            {output[:6000]}

            Allowed write paths:
            {chr(10).join(f"- {p}" for p in sorted(allowed_paths))}

            Hard constraints:
            1) Do not modify the immutable region of the task file.
            2) Keep changes minimal and scoped to resolving this failure.
            3) Do not modify files outside the allowlist unless they are already part of the task scope.
            4) After changes, validation target is only:
               {command}
            5) Return successfully only after applying the fix attempt.
            """
        ).strip()

        proc = subprocess.run(
            [
                "copilot",
                "--model",
                self.cfg.builder_model,
                "--autopilot",
                "--allow-all",
                "--max-autopilot-continues",
                str(self.cfg.build_max_autopilot_continues),
                "--no-ask-user",
                "--no-color",
                "--silent",
                "-p",
                prompt,
            ],
            cwd=self.state.issue.repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

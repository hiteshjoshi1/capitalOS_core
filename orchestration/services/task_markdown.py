from __future__ import annotations

import hashlib
from pathlib import Path


IMMUTABLE_END = "<!-- IMMUTABLE_PLAN_END -->"
MACHINE_START = "<!-- MACHINE_RENDERED_START -->"
MACHINE_END = "<!-- MACHINE_RENDERED_END -->"


DEFAULT_TEMPLATE = """# Issue {issue_id}: {title}

## Objective
- Define the problem clearly.

## Architecture Decisions
- Add the core design decisions here.

## Risks
- Add delivery or design risks here.

## Open Questions
- Add any open questions here.

## Acceptance Criteria
- Add concrete acceptance criteria here.

## Human Approval Gate
- [ ] Approved for implementation

{immutable_end}

{machine_start}
## Execution Journal
_Not rendered yet._
{machine_end}
"""


class TaskMarkdownService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = Path(repo_root)

    def _path(self, task_file: str) -> Path:
        return self.repo_root / task_file

    def read(self, task_file: str) -> str:
        return self._path(task_file).read_text()

    def write(self, task_file: str, content: str) -> None:
        path = self._path(task_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def bootstrap_if_missing(self, task_file: str, title: str, issue_id: str) -> None:
        path = self._path(task_file)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            DEFAULT_TEMPLATE.format(
                issue_id=issue_id,
                title=title,
                immutable_end=IMMUTABLE_END,
                machine_start=MACHINE_START,
                machine_end=MACHINE_END,
            )
        )

    def ensure_required_markers(self, task_file: str) -> None:
        content = self.read(task_file)
        if IMMUTABLE_END not in content:
            raise RuntimeError(f"Missing required immutable marker: {IMMUTABLE_END}")
        if MACHINE_START not in content or MACHINE_END not in content:
            updated = self.replace_machine_rendered_region(
                content,
                "## Execution Journal\n_Not rendered yet._",
            )
            self.write(task_file, updated)

    def immutable_region(self, content: str) -> str:
        if IMMUTABLE_END not in content:
            raise RuntimeError(f"Missing immutable marker: {IMMUTABLE_END}")
        before, _ = content.split(IMMUTABLE_END, 1)
        return before + IMMUTABLE_END

    def immutable_hash(self, content: str) -> str:
        region = self.immutable_region(content)
        return hashlib.sha256(region.encode()).hexdigest()

    def replace_machine_rendered_region(self, content: str, rendered: str) -> str:
        if MACHINE_START in content and MACHINE_END in content:
            prefix, rest = content.split(MACHINE_START, 1)
            _, suffix = rest.split(MACHINE_END, 1)
            return f"{prefix}{MACHINE_START}\n{rendered}\n{MACHINE_END}{suffix}"
        return f"{content.rstrip()}\n\n{MACHINE_START}\n{rendered}\n{MACHINE_END}\n"
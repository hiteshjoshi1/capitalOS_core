from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.services.task_markdown import (
    DEFAULT_TEMPLATE,
    IMMUTABLE_END,
    MACHINE_END,
    MACHINE_START,
    TaskMarkdownService,
)


def _write_task(tmp_path: Path, content: str) -> str:
    task_file = "tasks/issue-999-validation.md"
    path = tmp_path / task_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return task_file


def test_default_task_template_includes_how_to_test_before_immutable_marker() -> None:
    rendered = DEFAULT_TEMPLATE.format(
        issue_id="999",
        title="Validation",
        immutable_end=IMMUTABLE_END,
        machine_start=MACHINE_START,
        machine_end=MACHINE_END,
    )

    immutable_content, _ = rendered.split(IMMUTABLE_END, 1)

    assert "## How To Test" in immutable_content


def test_task_file_template_includes_how_to_test_before_immutable_marker() -> None:
    template_path = Path(__file__).resolve().parents[2] / "tasks" / "_template.md"
    template = template_path.read_text()
    immutable_content, _ = template.split(IMMUTABLE_END, 1)

    assert "## How To Test" in immutable_content


def test_missing_test_instructions_fail_with_actionable_message(tmp_path: Path) -> None:
    task_file = _write_task(
        tmp_path,
        f"""# Issue 999: Validation

## Objective
- Validate task docs.

## Acceptance Criteria
- Validation rejects missing test instructions.

{IMMUTABLE_END}
""",
    )

    with pytest.raises(RuntimeError) as exc_info:
        TaskMarkdownService(str(tmp_path)).ensure_required_markers(task_file)

    message = str(exc_info.value)
    assert task_file in message
    assert "## How To Test" in message
    assert "## Verification Plan" in message
    assert f"before `{IMMUTABLE_END}`" in message


def test_how_to_test_before_marker_passes_validation(tmp_path: Path) -> None:
    task_file = _write_task(
        tmp_path,
        f"""# Issue 999: Validation

## Objective
- Validate task docs.

## How To Test
- Run `make orch-test` and confirm tests pass.

{IMMUTABLE_END}
""",
    )

    TaskMarkdownService(str(tmp_path)).ensure_required_markers(task_file)


def test_inline_immutable_marker_reference_does_not_truncate_validation(tmp_path: Path) -> None:
    task_file = _write_task(
        tmp_path,
        f"""# Issue 999: Validation

## Objective
- Mention `{IMMUTABLE_END}` in prose before the real marker.

## How To Test
- Run `make orch-test` and confirm tests pass.

{IMMUTABLE_END}
""",
    )

    TaskMarkdownService(str(tmp_path)).ensure_required_markers(task_file)


def test_verification_plan_before_marker_passes_validation(tmp_path: Path) -> None:
    task_file = _write_task(
        tmp_path,
        f"""# Issue 999: Validation

## Objective
- Validate task docs.

## Verification Plan
- Run `make orch-test` and confirm tests pass.

{IMMUTABLE_END}
""",
    )

    TaskMarkdownService(str(tmp_path)).ensure_required_markers(task_file)


def test_how_to_test_after_marker_fails_validation(tmp_path: Path) -> None:
    task_file = _write_task(
        tmp_path,
        f"""# Issue 999: Validation

## Objective
- Validate task docs.

{IMMUTABLE_END}

## How To Test
- Run `make orch-test` and confirm tests pass.
""",
    )

    with pytest.raises(RuntimeError, match="before `<!-- IMMUTABLE_PLAN_END -->`"):
        TaskMarkdownService(str(tmp_path)).ensure_required_markers(task_file)

from __future__ import annotations

import sys
from typing import Iterable, TextIO


def _stage_name(stage: object | None) -> str | None:
    if stage is None:
        return None
    return getattr(stage, "value", str(stage))


def _emit_line(line: str, stream: TextIO) -> None:
    print(line, file=stream, flush=True)


def emit_event(
    event: str,
    *,
    stage: object | None = None,
    status: str | None = None,
    current_action: str | None = None,
    actions_taken: Iterable[str] | None = None,
    evidence: Iterable[str] | None = None,
    reasoning: str | None = None,
    conclusion: str | None = None,
    stream: TextIO | None = None,
) -> None:
    stream = stream or sys.stderr
    parts = [f"event={event}"]
    stage_name = _stage_name(stage)
    if stage_name:
        parts.append(f"stage={stage_name}")
    if status:
        parts.append(f"status={status}")
    _emit_line(f"[orchestration] {' '.join(parts)}", stream)

    if current_action:
        _emit_line(f"[orchestration]   current_action: {current_action}", stream)
    for action in actions_taken or []:
        _emit_line(f"[orchestration]   action_taken: {action}", stream)
    for item in evidence or []:
        _emit_line(f"[orchestration]   evidence: {item}", stream)
    if reasoning:
        _emit_line(f"[orchestration]   reasoning: {reasoning}", stream)
    if conclusion:
        _emit_line(f"[orchestration]   conclusion: {conclusion}", stream)


def emit_stage_start(
    stage: object,
    *,
    current_action: str,
    evidence: Iterable[str] | None = None,
    reasoning: str | None = None,
) -> None:
    emit_event(
        "stage_start",
        stage=stage,
        status="running",
        current_action=current_action,
        evidence=evidence,
        reasoning=reasoning,
    )


def emit_stage_end(
    stage: object,
    *,
    status: str,
    conclusion: str,
    evidence: Iterable[str] | None = None,
) -> None:
    emit_event(
        "stage_end",
        stage=stage,
        status=status,
        evidence=evidence,
        conclusion=conclusion,
    )


def emit_progress(
    stage: object,
    *,
    current_action: str,
    actions_taken: Iterable[str] | None = None,
    evidence: Iterable[str] | None = None,
    reasoning: str | None = None,
) -> None:
    emit_event(
        "progress",
        stage=stage,
        current_action=current_action,
        actions_taken=actions_taken,
        evidence=evidence,
        reasoning=reasoning,
    )


def emit_waiting_for_human(
    stage: object,
    *,
    gate: str,
    evidence: Iterable[str] | None = None,
    conclusion: str | None = None,
) -> None:
    emit_event(
        "waiting_for_human",
        stage=stage,
        status="waiting_for_human",
        current_action=f"Waiting for human input at `{gate}`",
        evidence=evidence,
        conclusion=conclusion,
    )

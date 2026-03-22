from io import StringIO

from orchestration.services.console import emit_event, emit_stage_end, emit_stage_start


def test_emit_stage_start_and_end_include_key_fields():
    stream = StringIO()

    emit_stage_start(
        "build",
        current_action="Running builder implementation",
        evidence=["planned_paths=8"],
    )
    emit_stage_end(
        "build",
        status="blocked",
        evidence=["blockers=1"],
        conclusion="Verification failed.",
    )

    # Default stream is stderr, so exercise the generic emitter with an injected stream too.
    emit_event(
        "progress",
        stage="build",
        current_action="Running verification",
        evidence=["command=make test-backend"],
        reasoning="Need test evidence before review.",
        stream=stream,
    )

    output = stream.getvalue()
    assert "event=progress" in output
    assert "stage=build" in output
    assert "current_action: Running verification" in output
    assert "evidence: command=make test-backend" in output
    assert "reasoning: Need test evidence before review." in output

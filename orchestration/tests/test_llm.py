from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.services.llm import LLMService
from orchestration.services.llm import (
    _extract_first_json_value,
    _extract_json_with_fallback,
    _iter_session_event_files,
    _session_metadata,
    extract_latest_assistant_message,
    extract_session_repair_context,
    extract_structured_plan_output,
    find_latest_copilot_session,
    wait_for_latest_assistant_message,
)


PLAN_JSON = """
{
  "summary": "Fix risk card plan",
  "architecture_decisions": ["Keep parser tolerant of wrapper text"],
  "risks": ["Model may add prose around JSON"],
  "open_questions": ["Should this be generalized later?"],
  "acceptance_criteria": ["Plan output parses successfully"],
  "planned_paths": ["orchestration/services/llm.py"],
  "checklist": [
    {
      "id": "CHK-1",
      "text": "Parse the model output",
      "required": true,
      "human_only": false,
      "post_ship": false,
      "planned_paths": ["orchestration/services/llm.py"]
    }
  ]
}
""".strip()


def test_extract_structured_plan_output_accepts_raw_json() -> None:
    plan = extract_structured_plan_output(PLAN_JSON)
    assert plan.summary == "Fix risk card plan"
    assert plan.checklist[0].id == "CHK-1"


def test_extract_structured_plan_output_accepts_fenced_json_with_prose() -> None:
    raw = f"Here is the plan:\n\n```json\n{PLAN_JSON}\n```"
    plan = extract_structured_plan_output(raw)
    assert plan.summary == "Fix risk card plan"
    assert plan.planned_paths == ["orchestration/services/llm.py"]


def test_extract_structured_plan_output_accepts_embedded_json_object() -> None:
    raw = f"Planner notes before payload\n{PLAN_JSON}\nPlanner notes after payload"
    plan = extract_structured_plan_output(raw)
    assert plan.acceptance_criteria == ["Plan output parses successfully"]


def test_extract_structured_plan_output_uses_last_valid_fenced_json_block() -> None:
    bad_json = """
{
  "summary": "Broken plan",
  "architecture_decisions": ["unterminated
}
""".strip()
    raw = (
        "Interim attempt follows.\n\n"
        f"```json\n{bad_json}\n```\n\n"
        "Retry succeeded.\n\n"
        f"```json\n{PLAN_JSON}\n```"
    )
    plan = extract_structured_plan_output(raw)
    assert plan.summary == "Fix risk card plan"
    assert plan.planned_paths == ["orchestration/services/llm.py"]


def test_extract_structured_plan_output_uses_fallback_payload_when_stdout_is_corrupted() -> None:
    raw = "tool chatter\npartial json starts here {\nretry banner\n"
    plan = extract_structured_plan_output(raw, PLAN_JSON)
    assert plan.summary == "Fix risk card plan"
    assert plan.checklist[0].id == "CHK-1"


def test_extract_structured_plan_output_raises_when_no_json_present() -> None:
    with pytest.raises(RuntimeError, match="Model did not return valid JSON"):
        extract_structured_plan_output("Here is the plan, but no structured payload followed.")


def test_extract_first_json_value_accepts_json_array() -> None:
    assert _extract_first_json_value('[{"ok": true}]') == [{"ok": True}]


def test_extract_first_json_value_scans_embedded_json() -> None:
    raw = "prefix noise {\"summary\": \"ok\"} suffix"
    assert _extract_first_json_value(raw) == {"summary": "ok"}


def test_extract_json_with_fallback_raises_with_original_raw() -> None:
    with pytest.raises(RuntimeError, match="Model did not return valid JSON"):
        _extract_json_with_fallback("bad", "still bad")


def test_iter_session_event_files_returns_sorted_paths(tmp_path, monkeypatch) -> None:
    root = tmp_path / ".copilot" / "session-state"
    first = root / "a" / "events.jsonl"
    second = root / "b" / "events.jsonl"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("")
    second.write_text("")
    first.touch()
    second.touch()

    monkeypatch.setattr("orchestration.services.llm.Path.home", lambda: tmp_path)

    paths = _iter_session_event_files()
    assert paths[0] == second
    assert paths[1] == first


def test_session_metadata_handles_invalid_and_valid_payloads(tmp_path):
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{not-json}\n")
    assert _session_metadata(invalid) is None

    wrong_type = tmp_path / "wrong.jsonl"
    wrong_type.write_text('{"type":"assistant.message"}\n')
    assert _session_metadata(wrong_type) is None

    valid = tmp_path / "valid.jsonl"
    valid.write_text(
        '{"type":"session.start","data":{"selectedModel":"gpt","context":{"cwd":"/tmp/repo","branch":"main"}}}\n'
    )
    assert _session_metadata(valid) == {"model": "gpt", "cwd": "/tmp/repo", "branch": "main"}


def test_find_latest_copilot_session_filters_by_model_root_and_branch(tmp_path, monkeypatch):
    root = tmp_path / ".copilot" / "session-state"
    bad_model = root / "a" / "events.jsonl"
    bad_root = root / "b" / "events.jsonl"
    good = root / "c" / "events.jsonl"
    for path in (bad_model, bad_root, good):
        path.parent.mkdir(parents=True, exist_ok=True)

    bad_model.write_text(
        '{"type":"session.start","data":{"selectedModel":"other","context":{"cwd":"/tmp/repo","branch":"feature"}}}\n'
    )
    bad_root.write_text(
        '{"type":"session.start","data":{"selectedModel":"target","context":{"cwd":"/tmp/other","branch":"feature"}}}\n'
    )
    good.write_text(
        '{"type":"session.start","data":{"selectedModel":"target","context":{"cwd":"/tmp/repo","branch":"feature"}}}\n'
    )
    monkeypatch.setattr("orchestration.services.llm.Path.home", lambda: tmp_path)

    result = find_latest_copilot_session(
        model="target",
        repo_root="/tmp/repo",
        branch="feature",
    )

    assert result == good


def test_extract_latest_assistant_message_returns_last_message(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"assistant.message","data":{"content":"first"}}',
                '{"type":"tool.message","data":{"content":"ignore"}}',
                '{"type":"assistant.message","data":{"content":"second"}}',
            ]
        )
    )

    assert extract_latest_assistant_message(path) == "second"


def test_extract_latest_assistant_message_returns_none_on_missing_file(tmp_path):
    assert extract_latest_assistant_message(tmp_path / "missing.jsonl") is None


def test_wait_for_latest_assistant_message_can_wait_for_json(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("")
    path.write_text(
        "\n".join(
            [
                '{"type":"assistant.message","data":{"content":"tool chatter only"}}',
                '{"type":"assistant.message","data":{"content":"```json\\n{\\"summary\\": \\"ok\\"}\\n```"}}',
            ]
        )
    )

    result = wait_for_latest_assistant_message(path, timeout_seconds=0.1, poll_interval_seconds=0.01, require_json=True)

    assert result is not None
    assert '{"summary": "ok"}' in result


def test_extract_session_repair_context_summarizes_completed_tools_session(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":"assistant.message","data":{"content":"Ground truth established."}}',
                '{"type":"tool.execution_complete","data":{"result":{"content":"18 passed (18)"}}}',
                '{"type":"session.task_complete","data":{"summary":"All rework changes applied and verified. JSON response below."}}',
                '{"type":"session.shutdown","data":{"codeChanges":{"linesAdded":10,"linesRemoved":9,"filesModified":["web/src/App.tsx","web/src/__tests__/App.test.tsx"]}}}',
            ]
        )
    )

    context = extract_session_repair_context(path)

    assert context is not None
    assert "Task-complete summary: All rework changes applied and verified. JSON response below." in context
    assert "- web/src/App.tsx" in context
    assert "- web/src/__tests__/App.test.tsx" in context
    assert "Line changes: +10 / -9" in context
    assert "- Ground truth established." in context
    assert "- 18 passed (18)" in context


def test_build_uses_autopilot_when_tools_enabled(monkeypatch) -> None:
    calls = []

    class FakeConfig:
        copilot_tool_mode = "tools-enabled"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-sonnet-4.5"

    class FakePopen:
        def __init__(self, args, stdout, stderr, text, cwd, **kwargs):
            calls.append((args, cwd))
            self.returncode = 0
            self.stdout = StringIO('{"summary":"ok"}')
            self.stderr = StringIO("")

        def poll(self):
            return None

        def wait(self):
            return self.returncode

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())
    monkeypatch.setattr("orchestration.services.llm.subprocess.Popen", FakePopen)

    service = LLMService(PipelineStage.BUILD, repo_root="/tmp/repo")
    service.complete_text("Implement the task")

    args, cwd = calls[0]
    assert "--autopilot" in args
    assert "--allow-all" in args
    assert cwd == "/tmp/repo"


def test_plan_stays_text_only_even_when_tools_enabled(monkeypatch) -> None:
    calls = []

    class FakeConfig:
        copilot_tool_mode = "tools-enabled"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-opus-4.6"

    class FakePopen:
        def __init__(self, args, stdout, stderr, text, cwd, **kwargs):
            calls.append((args, cwd))
            self.returncode = 0
            self.stdout = StringIO(PLAN_JSON)
            self.stderr = StringIO("")

        def poll(self):
            return None

        def wait(self):
            return self.returncode

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())
    monkeypatch.setattr("orchestration.services.llm.subprocess.Popen", FakePopen)

    service = LLMService(PipelineStage.PLAN, repo_root="/tmp/repo")
    service.complete_text("Plan the task")

    args, cwd = calls[0]
    assert "--autopilot" not in args
    assert "--no-ask-user" in args
    assert cwd == "/tmp/repo"


def test_complete_text_raises_when_copilot_fails(monkeypatch):
    class FakeConfig:
        copilot_tool_mode = "text-only"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-opus-4.6"

    class FakePopen:
        def __init__(self, args, stdout, stderr, text, cwd, bufsize):
            self.returncode = 1
            self.stdout = StringIO("")
            self.stderr = StringIO("copilot exploded")

        def wait(self):
            return self.returncode

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())
    monkeypatch.setattr("orchestration.services.llm.subprocess.Popen", FakePopen)
    monkeypatch.setattr("orchestration.services.llm.emit_event", lambda *args, **kwargs: None)

    service = LLMService(PipelineStage.PLAN, repo_root="/tmp/repo")
    with pytest.raises(RuntimeError, match="Copilot subprocess failed during `plan`"):
        service.complete_text("Plan it")


def test_complete_structured_validates_non_plan_models(monkeypatch):
    class ExampleModel(PlanOutput):
        pass

    class FakeConfig:
        copilot_tool_mode = "text-only"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-opus-4.6"

    class FakePopen:
        def __init__(self, args, stdout, stderr, text, cwd, bufsize):
            self.returncode = 0
            self.stdout = StringIO(PLAN_JSON)
            self.stderr = StringIO("")

        def wait(self):
            return self.returncode

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())
    monkeypatch.setattr("orchestration.services.llm.subprocess.Popen", FakePopen)
    monkeypatch.setattr("orchestration.services.llm.find_latest_copilot_session", lambda **kwargs: None)

    service = LLMService(PipelineStage.PLAN, repo_root="/tmp/repo")
    parsed = service.complete_structured("Plan the task", ExampleModel)

    assert parsed.summary == "Fix risk card plan"


def test_complete_structured_uses_session_fallback_when_streamed_stdout_is_invalid(monkeypatch) -> None:
    class FakeConfig:
        copilot_tool_mode = "tools-enabled"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-opus-4.6"

    class FakePopen:
        def __init__(self, args, stdout, stderr, text, cwd, **kwargs):
            self.returncode = 0
            self.stdout = StringIO("tool chatter\npartial json {\nretry...\n")
            self.stderr = StringIO("")

        def wait(self):
            return self.returncode

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())
    monkeypatch.setattr("orchestration.services.llm.subprocess.Popen", FakePopen)
    monkeypatch.setattr(
        "orchestration.services.llm.find_latest_copilot_session",
        lambda **kwargs: Path("/tmp/fake-session/events.jsonl"),
    )
    monkeypatch.setattr(
        "orchestration.services.llm.extract_latest_assistant_message",
        lambda path: f"```json\n{PLAN_JSON}\n```",
    )

    service = LLMService(PipelineStage.PLAN, repo_root="/tmp/repo")
    plan = service.complete_structured("Plan the task", PlanOutput)

    assert plan.summary == "Fix risk card plan"
    assert service.last_session_events_path == Path("/tmp/fake-session/events.jsonl")


def test_complete_structured_repairs_when_tools_session_ends_without_final_json(monkeypatch, tmp_path) -> None:
    class ExampleModel(BaseModel):
        summary: str
        changed_files: list[str]

    class FakeConfig:
        copilot_tool_mode = "tools-enabled"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-sonnet-4.6"

    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                '{"type":"assistant.message","data":{"content":""}}',
                '{"type":"session.task_complete","data":{"summary":"All rework changes applied and verified. JSON response below."}}',
                '{"type":"session.shutdown","data":{"codeChanges":{"linesAdded":3,"linesRemoved":3,"filesModified":["web/src/App.tsx"]}}}',
            ]
        )
    )

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())

    calls: list[tuple[str, bool]] = []

    def fake_complete_text_with_mode(self, prompt: str, *, tools_enabled: bool) -> str:
        calls.append((prompt, tools_enabled))
        if tools_enabled:
            self.last_session_events_path = events_path
            return ""
        return '{"summary":"repaired","changed_files":["web/src/App.tsx"]}'

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService._complete_text_with_mode",
        fake_complete_text_with_mode,
    )

    service = LLMService(PipelineStage.REWORK_IMPLEMENTATION, repo_root="/tmp/repo")
    parsed = service.complete_structured("Return strict JSON only.", ExampleModel)

    assert parsed.summary == "repaired"
    assert parsed.changed_files == ["web/src/App.tsx"]
    assert calls[0][1] is True
    assert calls[1][1] is False
    assert "did not emit the required final JSON payload" in calls[1][0]
    assert "Modified files:" in calls[1][0]


def test_complete_structured_waits_for_delayed_session_json_before_repair(monkeypatch, tmp_path) -> None:
    class ExampleModel(BaseModel):
        summary: str

    class FakeConfig:
        copilot_tool_mode = "tools-enabled"
        build_max_autopilot_continues = 12

        def model_for_stage(self, stage):
            return "claude-sonnet-4.6"

    monkeypatch.setattr("orchestration.services.llm.get_config", lambda: FakeConfig())

    calls: list[tuple[str, bool]] = []

    def fake_complete_text_with_mode(self, prompt: str, *, tools_enabled: bool) -> str:
        calls.append((prompt, tools_enabled))
        self.last_session_events_path = tmp_path / "events.jsonl"
        return "tool chatter\nnot json\n"

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService._complete_text_with_mode",
        fake_complete_text_with_mode,
    )
    monkeypatch.setattr(
        "orchestration.services.llm.wait_for_latest_assistant_message",
        lambda *args, **kwargs: '{"summary":"from-session"}',
    )

    service = LLMService(PipelineStage.REWORK_IMPLEMENTATION, repo_root="/tmp/repo")
    parsed = service.complete_structured("Return strict JSON only.", ExampleModel)

    assert parsed.summary == "from-session"
    assert calls == [("Return strict JSON only.", True)]

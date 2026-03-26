from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.services.llm import LLMService
from orchestration.services.llm import extract_structured_plan_output


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

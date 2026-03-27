from __future__ import annotations

from orchestration.services.restore import RestoreBootstrapService
from orchestration.services.state_io import StateIOService


def test_export_state_includes_metadata(tmp_path):
    service = StateIOService(str(tmp_path))

    exported_path = service.export_state(
        "issue-123",
        {
            "pipeline": {
                "current_stage": "human_review",
                "workflow_status": "waiting_for_human",
            },
            "next": ("human_review",),
            "interrupts": [{"gate": "human_review", "review_id": "R1"}],
        },
    )

    payload = service.import_state(exported_path)

    assert payload["export_metadata"]["schema_version"] == 2
    assert payload["export_metadata"]["source_thread_id"] == "issue-123"
    assert payload["export_metadata"]["source_stage"] == "human_review"
    assert payload["export_metadata"]["source_workflow_status"] == "waiting_for_human"
    assert payload["export_metadata"]["source_interrupts"] == [
        {"gate": "human_review", "review_id": "R1"}
    ]


def test_restore_uses_interrupt_metadata_for_human_gate():
    payload = {
        "export_metadata": {
            "schema_version": 2,
            "source_thread_id": "issue-123",
            "source_stage": "human_review",
            "source_workflow_status": "waiting_for_human",
            "source_interrupts": [{"gate": "extra_files_approval", "review_id": "R7"}],
        },
        "pipeline": {
            "issue": {
                "issue_id": "123",
                "slug": "test",
                "title": "Test",
                "task_file": "tasks/issue-123-test.md",
                "repo_root": "/tmp/repo",
                "branch": "feature/issue-123-test",
                "created_at": "2026-03-18T00:00:00Z",
            },
            "current_stage": "human_review",
            "workflow_status": "waiting_for_human",
            "requested_entrypoint": "build",
            "execution_mode": "step",
            "review_cycles": [],
            "rework_cycles": [],
            "human_gate_decisions": {},
            "approved_extra_files": [],
            "blockers": [],
            "errors": [],
            "retry_log": [],
            "updated_at": "2026-03-18T00:00:00Z",
        },
        "next": ["human_review"],
        "interrupts": [{"gate": "extra_files_approval", "review_id": "R7"}],
    }

    restored = RestoreBootstrapService.from_export(
        payload,
        restart_at="human_review",
    )

    assert restored["pipeline"]["requested_entrypoint"] == "human_review"
    assert restored["pipeline"]["execution_mode"] == "workflow"

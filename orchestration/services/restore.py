from __future__ import annotations

from typing import Any

from orchestration.models.pipeline import PipelineState


class RestoreBootstrapService:
    """
    Converts exported portable state into a fresh graph bootstrap state.

    This does NOT try to restore internal LangGraph checkpoint machinery.
    It starts a fresh thread with a reconstructed PipelineState and an
    explicitly chosen entrypoint.
    """

    @staticmethod
    def from_export(
        exported_payload: dict[str, Any],
        *,
        restart_at: str,
        execution_mode: str = "workflow",
    ) -> dict[str, Any]:
        if "pipeline" in exported_payload:
            raw_pipeline = exported_payload["pipeline"]
        elif "values" in exported_payload and "pipeline" in exported_payload["values"]:
            raw_pipeline = exported_payload["values"]["pipeline"]
        else:
            raise RuntimeError(
                "Exported state does not contain portable pipeline state."
            )

        pipeline = PipelineState.model_validate(raw_pipeline)
        metadata = exported_payload.get("export_metadata") or {}
        effective_restart_at = restart_at
        interrupts = metadata.get("source_interrupts") or exported_payload.get("interrupts") or []
        if effective_restart_at in {"human_review", "human_approval_gate"} and interrupts:
            gate = interrupts[0].get("gate")
            if gate == "plan_approval":
                effective_restart_at = "human_approval_gate"
            elif gate in {"human_review", "extra_files_approval"}:
                effective_restart_at = "human_review"

        pipeline.requested_entrypoint = effective_restart_at  # type: ignore[assignment]
        pipeline.execution_mode = execution_mode    # type: ignore[assignment]

        # Reset transient workflow flags so the new thread can continue cleanly.
        if pipeline.workflow_status in {"waiting_for_human", "failed", "blocked"}:
            pipeline.workflow_status = "running"

        # If restoring at human gates, keep active review/rework ids as-is.
        pipeline.current_stage = "dispatch"

        return {"pipeline": pipeline.model_dump(mode="json")}

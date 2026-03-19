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
        pipeline.requested_entrypoint = restart_at  # type: ignore[assignment]
        pipeline.execution_mode = execution_mode    # type: ignore[assignment]

        # Reset transient workflow flags so the new thread can continue cleanly.
        if pipeline.workflow_status in {"waiting_for_human", "failed", "blocked"}:
            pipeline.workflow_status = "running"

        # If restoring at human gates, keep active review/rework ids as-is.
        pipeline.current_stage = "dispatch"

        return {"pipeline": pipeline.model_dump(mode="json")}
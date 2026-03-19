from __future__ import annotations

from typing import Any, Dict, TypedDict

from orchestration.models.pipeline import PipelineState


class GraphState(TypedDict):
    pipeline: Dict[str, Any]


def load_pipeline_state(state: GraphState) -> PipelineState:
    return PipelineState.model_validate(state["pipeline"])


def dump_pipeline_state(pipeline: PipelineState) -> GraphState:
    pipeline.touch()
    return {"pipeline": pipeline.model_dump(mode="json")}
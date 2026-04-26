from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from app.rag.ingestion.parser import StructuredParseResult


def _copy(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return deepcopy(value) if value is not None else None


def apply_source_preset(
    *,
    author_id: str,
    url: Optional[str],
    ingestion_config: Optional[dict[str, Any]] = None,
    selective_options: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """
    Generic passthrough helper.

    Source-specific ingestion behavior must be supplied explicitly via
    ingestion_config/selective_options by the caller; the application should
    not silently infer corpus rules from hardcoded URLs or author IDs.
    """

    del author_id, url
    return _copy(ingestion_config), _copy(selective_options)


def normalize_source_parse_result(source_url: Optional[str], parsed: StructuredParseResult) -> StructuredParseResult:
    """
    Generic passthrough normalizer.

    Parsing/section handling should remain source-agnostic unless the caller
    supplies explicit transformation rules as part of ingestion config.
    """

    del source_url
    return parsed

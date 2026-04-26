from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.rag.ingestion.parser import DocumentSection, StructuredParseResult


def normalize_with_ingestion_config(
    parsed: StructuredParseResult,
    ingestion_config: dict[str, Any] | None,
) -> StructuredParseResult:
    if not ingestion_config:
        return parsed

    section_splits = ingestion_config.get("section_splits")
    if not isinstance(section_splits, list) or not section_splits:
        return parsed

    normalized = deepcopy(parsed)
    normalized.sections = apply_section_splits(list(parsed.sections or []), section_splits)
    return normalized


def apply_section_splits(
    sections: list[DocumentSection],
    section_splits: list[dict[str, Any]],
) -> list[DocumentSection]:
    if not section_splits:
        return sections

    result: list[DocumentSection] = []
    for section in sections:
        applied = False
        for rule in section_splits:
            if rule.get("match_heading") != section.heading:
                continue
            split_sections = _split_section_by_markers(section, rule.get("markers") or [])
            if split_sections is None:
                break
            result.extend(split_sections)
            applied = True
            break
        if not applied:
            result.append(section)
    return result


def _split_section_by_markers(
    section: DocumentSection,
    markers: list[dict[str, Any]],
) -> list[DocumentSection] | None:
    if not markers:
        return None

    content = section.content or ""
    positions: list[tuple[int, dict[str, Any]]] = []
    search_start = 0
    for marker in markers:
        marker_text = str(marker.get("marker") or "").strip()
        if not marker_text:
            return None
        position = content.find(marker_text, search_start)
        if position < 0:
            return None
        positions.append((position, marker))
        search_start = position + len(marker_text)

    split_sections: list[DocumentSection] = [
        DocumentSection(
            heading=section.heading,
            level=section.level,
            content=content[: positions[0][0]].strip(),
            content_type=section.content_type,
            table_markdown=section.table_markdown,
        )
    ]

    for index, (position, marker) in enumerate(positions):
        marker_text = str(marker.get("marker") or "")
        next_position = positions[index + 1][0] if index + 1 < len(positions) else len(content)
        body = content[position + len(marker_text) : next_position].strip()
        split_sections.append(
            DocumentSection(
                heading=str(marker.get("heading") or marker_text),
                level=int(marker.get("level") or section.level),
                content=body,
                content_type=section.content_type,
                table_markdown=None,
            )
        )

    return split_sections
